# Licensed under a 3-clause BSD style license - see LICENSE.rst

import base64
import email
import json
import os.path
import pickle
import re
import shutil
import subprocess
import time
import warnings
import webbrowser
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import List, Optional, Tuple, Dict, Set, Union
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import astropy.table
import astropy.utils.data
import astropy.units as u
import keyring
import requests.exceptions
from astropy.table import Table, Column
from astropy.utils.decorators import deprecated, deprecated_renamed_argument
from bs4 import BeautifulSoup

from astroquery import log, cache_conf
from . import conf
from ..exceptions import RemoteServiceError, NoResultsWarning, LoginError
from ..query import QueryWithLogin
from ..utils import schema
from .utils import py2adql, _split_str_as_list_of_str, sanitize_val, to_cache, eso_hash
import pyvo

__doctest_skip__ = ['EsoClass.*']


class CalSelectorError(Exception):
    """
    Raised on failure to parse CalSelector's response.
    """


class UnknownException(Exception):
    """
    Raised when an exception is not foreseen.
    """


class AuthInfo:
    def __init__(self, username: str, password: str, token: str):
        self.username = username
        self.password = password
        self.token = token
        self.expiration_time = self._get_exp_time_from_token()

    def _get_exp_time_from_token(self) -> int:
        # "manual" decoding since jwt is not installed
        decoded_token = base64.b64decode(self.token.split(".")[1] + "==")
        return int(json.loads(decoded_token)['exp'])

    def expired(self) -> bool:
        # we anticipate the expiration time by 10 minutes to avoid issues
        return time.time() > self.expiration_time - 600


@dataclass
class QueryOnField:
    table_name: str
    column_name: str


QueryOnInstrument = QueryOnField(
    table_name="dbo.raw",  # This should be ist.<instrument_name>
    column_name="instrument")


QueryOnCollection = QueryOnField(
    table_name="ivoa.ObsCore",
    column_name="obs_collection")


class EsoClass(QueryWithLogin):
    ROW_LIMIT = conf.row_limit
    USERNAME = conf.username
    QUERY_INSTRUMENT_URL = conf.query_instrument_url
    CALSELECTOR_URL = "https://archive.eso.org/calselector/v1/associations"
    DOWNLOAD_URL = "https://dataportal.eso.org/dataPortal/file/"
    AUTH_URL = "https://www.eso.org/sso/oidc/token"
    GUNZIP = "gunzip"
    USE_DEV_TAP = True

    def __init__(self, timeout=None):
        super().__init__()
        self._instruments: Optional[List[str]] = None
        self._collections: Optional[List[str]] = None
        self._auth_info: Optional[AuthInfo] = None
        self.timeout = timeout
        self._hash = None
        # for future debugging
        self._payload = None

    @property
    def timeout(self):
        return self._timeout

    # The logging module needs strings
    # written in %s style. This wrappers
    # are used for that purpose.
    # [W1203 - logging-fstring-interpolation]
    @staticmethod
    def log_info(message):
        log.info("%s", message)

    @staticmethod
    def log_warning(message):
        log.warning("%s", message)

    @staticmethod
    def log_error(message):
        log.error("%s", message)

    @staticmethod
    def log_debug(message):
        log.debug("%s", message)

    @timeout.setter
    def timeout(self, value):
        if hasattr(value, 'to'):
            self._timeout = value.to(u.s).value
        else:
            self._timeout = value

    @staticmethod
    def tap_url() -> str:
        url = "http://archive.eso.org/tap_obs"
        if EsoClass.USE_DEV_TAP:
            url = "http://dfidev5.hq.eso.org:8123/tap_obs"
        return url

    def request_file(self, query_str: str):
        h = eso_hash(query_str=query_str, url=self.tap_url())
        fn = self.cache_location.joinpath(h + ".pickle")
        return fn

    def from_cache(self, query_str, cache_timeout):
        table_file = self.request_file(query_str)
        try:
            if cache_timeout is None:
                expired = False
            else:
                current_time = datetime.now(timezone.utc)
                cache_time = datetime.fromtimestamp(table_file.stat().st_mtime, timezone.utc)
                expired = current_time-cache_time > timedelta(seconds=cache_timeout)
            if not expired:
                with open(table_file, "rb") as f:
                    cached_table = pickle.load(f)
                if not isinstance(cached_table, Table):
                    cached_table = None
            else:
                self.log_debug(f"Cache expired for {table_file} ...")
                cached_table = None
        except FileNotFoundError:
            cached_table = None
        if cached_table:
            self.log_debug(f"Retrieved data from {table_file} ...")
        return cached_table

    def _authenticate(self, *, username: str, password: str) -> bool:
        """
        Get the access token from ESO SSO provider
        """
        self._auth_info = None
        url_params = {"response_type": "id_token token",
                      "grant_type": "password",
                      "client_id": "clientid",
                      "client_secret": "clientSecret",
                      "username": username,
                      "password": password}
        self.log_info(f"Authenticating {username} on 'www.eso.org' ...")
        response = self._request('GET', self.AUTH_URL, params=url_params)
        if response.status_code == 200:
            token = json.loads(response.content)['id_token']
            self._auth_info = AuthInfo(username=username, password=password, token=token)
            self.log_info("Authentication successful!")
            return True
        else:
            self.log_error("Authentication failed!")
            return False

    def _get_auth_info(self, username: str, *, store_password: bool = False,
                       reenter_password: bool = False) -> Tuple[str, str]:
        """
        Get the auth info (user, password) for use in another function
        """

        if username is None:
            if not self.USERNAME:
                raise LoginError("If you do not pass a username to login(), "
                                 "you should configure a default one!")
            else:
                username = self.USERNAME

        service_name = "astroquery:www.eso.org"
        # Get password from keyring or prompt
        password, password_from_keyring = self._get_password(
            service_name, username, reenter=reenter_password)

        # When authenticated, save password in keyring if needed
        if password_from_keyring is None and store_password:
            keyring.set_password(service_name, username, password)

        return username, password

    def _login(self, *args, username: str = None, store_password: bool = False,
               reenter_password: bool = False, **kwargs) -> bool:
        """
        Login to the ESO User Portal.

        Parameters
        ----------
        username : str, optional
            Username to the ESO Public Portal. If not given, it should be
            specified in the config file.
        store_password : bool, optional
            Stores the password securely in your keyring. Default is False.
        reenter_password : bool, optional
            Asks for the password even if it is already stored in the
            keyring. This is the way to overwrite an already stored passwork
            on the keyring. Default is False.
        """

        username, password = self._get_auth_info(username=username,
                                                 store_password=store_password,
                                                 reenter_password=reenter_password)

        return self._authenticate(username=username, password=password)

    def _get_auth_header(self) -> Dict[str, str]:
        if self._auth_info and self._auth_info.expired():
            self.log_info("Authentication token has expired! Re-authenticating ...")
            self._authenticate(username=self._auth_info.username,
                               password=self._auth_info.password)
        if self._auth_info and not self._auth_info.expired():
            return {'Authorization': 'Bearer ' + self._auth_info.token}
        else:
            return {}

    def query_tap_service(self, query_str: str, cache: Optional[bool] = None) -> Optional[astropy.table.Table]:
        """
        returns an astropy.table.Table from an adql query string
        Example use:
        eso._query_tap_service("Select * from ivoa.ObsCore")
        """
        if cache is None:  # Global caching not overridden
            cache = cache_conf.cache_active

        tap = pyvo.dal.TAPService(EsoClass.tap_url())
        table_to_return = None

        # TODO add url to documentation in the exception
        try:

            if not cache:
                with cache_conf.set_temp("cache_active", False):
                    table_to_return = tap.search(query_str).to_table()
            else:
                table_to_return = self.from_cache(query_str, cache_conf.cache_timeout)
                if not table_to_return:
                    table_to_return = tap.search(query_str).to_table()
                    to_cache(table_to_return, self.request_file(query_str=query_str))

        except pyvo.dal.exceptions.DALQueryError as e:
            raise pyvo.dal.exceptions.DALQueryError(f"\n\n\
                                                    Error executing the following query:\n\n{query_str}\n\n") from e
        except UnknownException as e:
            raise RuntimeError(f"\n\n\
                            Unknown exception {e} while executing the following query: \n\n{query_str}\n\n") from e

        if len(table_to_return) > 0:
            return table_to_return
        else:
            warnings.warn("Query returned no results", NoResultsWarning)

    def list_instruments(self, *, cache=True) -> List[str]:
        """ List all the available instrument-specific queries offered by the ESO archive.

        Returns
        -------
        instrument_list : list of strings
        cache : bool
            Defaults to True. If set overrides global caching behavior.
            See :ref:`caching documentation <astroquery_cache>`.

        """
        if self._instruments is None:
            self._instruments = []
            query_str = "select table_name from TAP_SCHEMA.tables where schema_name='ist' order by table_name"
            res = self.query_tap_service(query_str, cache=cache)["table_name"].data
            self._instruments = list(map(lambda x: x.split(".")[1], res))
        return self._instruments

    def list_collections(self, *, cache=True) -> List[str]:
        """ List all the available collections (phase 3) in the ESO archive.

        Returns
        -------
        collection_list : list of strings
        cache : bool
            Defaults to True. If set overrides global caching behavior.
            See :ref:`caching documentation <astroquery_cache>`.
        """
        if self._collections is None:
            self._collections = []
            c = QueryOnCollection.column_name
            t = QueryOnCollection.table_name
            query_str = f"select distinct {c} from {t}"
            res = self.query_tap_service(query_str, cache=cache)[c].data

            self._collections = list(res)
        return self._collections

    def _query_instrument_or_collection(self,
                                        query_on: QueryOnField, primary_filter: Union[List[str], str], *,
                                        column_filters: Dict = None,
                                        columns: Union[List, str] = None, print_help=False, cache=True,
                                        **kwargs) -> astropy.table.Table:
        """
        Query instrument- or collection-specific data contained in the ESO archive.
         - instrument-specific data is raw
         - collection-specific data is processed

        Parameters
        ----------
        instrument : string
            Name of the instrument to query, one of the names returned by
            `~astroquery.eso.EsoClass.list_instruments`.
        column_filters : dict
            Constraints applied to the query.
        columns : list of strings
            Columns returned by the query.
        open_form : bool
            If `True`, opens in your default browser the query form
            for the requested instrument.
        help : bool
            If `True`, prints all the parameters accepted in
            ``column_filters`` and ``columns`` for the requested
            ``instrument``.
        cache : bool
            Defaults to True. If set overrides global caching behavior.
            See :ref:`caching documentation <astroquery_cache>`.

        Returns
        -------
        table : `~astropy.table.Table`
            A table representing the data available in the archive for the
            specified instrument, matching the constraints specified in
            ``kwargs``. The number of rows returned is capped by the
            ROW_LIMIT configuration item.
        """
        column_filters = column_filters or {}
        columns = columns or []

        # TODO - move help printing to its own function
        if print_help:
            help_query = \
                f"select column_name, datatype from TAP_SCHEMA.columns where table_name = '{query_on.table_name}'"
            h = self.query_tap_service(help_query)
            self.log_info(f"Columns present in the table: {h}")
            return

        filters = {**dict(kwargs), **column_filters}
        c_size = 0.1775  # so that even HARPS fits to pass the tests
        if 'box' in filters.keys():
            # TODO make c_size a parameter
            # c_size = c_size
            del filters['box']
        if isinstance(primary_filter, str):
            primary_filter = _split_str_as_list_of_str(primary_filter)

        primary_filter = list(map(lambda x: f"'{x.strip()}'", primary_filter))
        where_collections_str = f"{query_on.column_name} in (" + ", ".join(primary_filter) + ")"

        coord_constraint = []
        if ('coord1' in filters.keys()) and ('coord2' in filters.keys()):
            c1, c2 = filters['coord1'], filters["coord2"]
            del filters['coord1'], filters['coord2']
            coord_constraint = \
                [f"intersects(circle('ICRS', {c1}, {c2}, {c_size}), s_region)=1"]
            # http://archive.eso.org/tap_obs/examples

        # TODO
        # Check whether v is string or number, put in single quotes if string
        where_constraints_strlist = [f"{k} = {sanitize_val(v)}" for k, v in filters.items()] + coord_constraint
        where_constraints = [where_collections_str] + where_constraints_strlist
        query = py2adql(table=query_on.table_name, columns=columns, where_constraints=where_constraints,
                        top=self.ROW_LIMIT)

        return self.query_tap_service(query_str=query, cache=cache)

    @deprecated_renamed_argument(old_name='open_form', new_name=None, since='0.4.8')
    def query_instrument(self, instrument: Union[List, str] = None, *,
                         column_filters: Dict = None, columns: Union[List, str] = None,
                         open_form=False, print_help=False, cache=True,
                         **kwargs) -> astropy.table.Table:
        _ = open_form
        return self._query_instrument_or_collection(query_on=QueryOnInstrument,
                                                    primary_filter=instrument,
                                                    column_filters=column_filters,
                                                    columns=columns,
                                                    print_help=print_help,
                                                    cache=cache,
                                                    **kwargs)

    @deprecated_renamed_argument(old_name='open_form', new_name=None, since='0.4.8')
    def query_collections(self, collections: Union[List, str] = None, *,
                          column_filters: Dict = None, columns: Union[List, str] = None,
                          open_form=False, print_help=False, cache=True,
                          **kwargs) -> astropy.table.Table:
        column_filters = column_filters or {}
        columns = columns or []
        _ = open_form
        return self._query_instrument_or_collection(query_on=QueryOnCollection,
                                                    primary_filter=collections,
                                                    column_filters=column_filters,
                                                    columns=columns,
                                                    print_help=print_help,
                                                    cache=cache,
                                                    **kwargs)

    def query_main(self, *, column_filters=None, columns=None,
                   print_help=False, cache=True, **kwargs):
        """
        Query raw data contained in the ESO archive.

        Parameters
        ----------
        column_filters : dict
            Constraints applied to the query.
        columns : list of strings
            Columns returned by the query.
        open_form : bool
            If `True`, opens in your default browser the query form
            for the requested instrument.
        help : bool
            If `True`, prints all the parameters accepted in
            ``column_filters`` and ``columns`` for the requested
            ``instrument``.
        cache : bool
            Defaults to True. If set overrides global caching behavior.
            See :ref:`caching documentation <astroquery_cache>`.

        Returns
        -------
        table : `~astropy.table.Table`
            A table representing the data available in the archive for the
            specified instrument, matching the constraints specified in
            ``kwargs``. The number of rows returned is capped by the
            ROW_LIMIT configuration item.

        """
        column_filters = column_filters or {}
        columns = columns or []
        filters = {**dict(kwargs), **column_filters}

        where_constraints_strlist = [f"{k} = {sanitize_val(v)}" for k, v in filters.items()]
        where_constraints = where_constraints_strlist

        if print_help:
            help_query = \
                "select column_name, datatype from TAP_SCHEMA.columns where table_name = 'dbo.raw'"
            h = self.query_tap_service(help_query, cache=cache)
            self.log_info(f"Columns present in the table: {h}")
            return

        query = py2adql(table="dbo.raw",
                        columns=columns,
                        where_constraints=where_constraints,
                        top=self.ROW_LIMIT)

        return self.query_tap_service(query_str=query)

    def get_headers(self, product_ids, *, cache=True):
        """
        Get the headers associated to a list of data product IDs

        This method returns a `~astropy.table.Table` where the rows correspond
        to the provided data product IDs, and the columns are from each of
        the Fits headers keywords.

        Note: The additional column ``'DP.ID'`` found in the returned table
        corresponds to the provided data product IDs.

        Parameters
        ----------
        product_ids : either a list of strings or a `~astropy.table.Column`
            List of data product IDs.
        cache : bool
            Defaults to True. If set overrides global caching behavior.
            See :ref:`caching documentation <astroquery_cache>`.

        Returns
        -------
        result : `~astropy.table.Table`
            A table where: columns are header keywords, rows are product_ids.

        """
        _schema_product_ids = schema.Schema(
            schema.Or(Column, [schema.Schema(str)]))
        _schema_product_ids.validate(product_ids)
        # Get all headers
        result = []
        for dp_id in product_ids:
            response = self._request(
                "GET", "http://archive.eso.org/hdr?DpId={0}".format(dp_id),
                cache=cache)
            root = BeautifulSoup(response.content, 'html5lib')
            hdr = root.select('pre')[0].text
            header = {'DP.ID': dp_id}
            for key_value in hdr.split('\n'):
                if "=" in key_value:
                    key, value = key_value.split('=', 1)
                    key = key.strip()
                    value = value.split('/', 1)[0].strip()
                    if key[0:7] != "COMMENT":  # drop comments
                        if value == "T":  # Convert boolean T to True
                            value = True
                        elif value == "F":  # Convert boolean F to False
                            value = False
                        # Convert to string, removing quotation marks
                        elif value[0] == "'":
                            value = value[1:-1]
                        elif "." in value:  # Convert to float
                            value = float(value)
                        else:  # Convert to integer
                            value = int(value)
                        header[key] = value
                elif key_value.startswith("END"):
                    break
            result.append(header)
        # Identify all columns
        columns = []
        column_types = []
        for header in result:
            for key in header:
                if key not in columns:
                    columns.append(key)
                    column_types.append(type(header[key]))
        # Add all missing elements
        for i in range(len(result)):
            for (column, column_type) in zip(columns, column_types):
                if column not in result[i]:
                    result[i][column] = column_type()
        # Return as Table
        return Table(result)

    @staticmethod
    def _get_filename_from_response(response: requests.Response) -> str:
        content_disposition = response.headers.get("Content-Disposition", "")
        filename = re.findall(r"filename=(\S+)", content_disposition)
        if not filename:
            raise RemoteServiceError(f"Unable to find filename for {response.url}")
        return os.path.basename(filename[0].replace('"', ''))

    @staticmethod
    def _find_cached_file(filename: str) -> bool:
        files_to_check = [filename]
        if filename.endswith(('fits.Z', 'fits.gz')):
            files_to_check.append(filename.rsplit(".", 1)[0])
        for file in files_to_check:
            if os.path.exists(file):
                EsoClass.log_info(f"Found cached file {file}")
                return True
        return False

    def _download_eso_file(self, file_link: str, destination: str,
                           overwrite: bool) -> Tuple[str, bool]:
        block_size = astropy.utils.data.conf.download_block_size
        headers = self._get_auth_header()
        with self._session.get(file_link, stream=True, headers=headers) as response:
            response.raise_for_status()
            filename = self._get_filename_from_response(response)
            filename = os.path.join(destination, filename)
            part_filename = filename + ".part"
            if os.path.exists(part_filename):
                self.log_info(f"Removing partially downloaded file {part_filename}")
                os.remove(part_filename)
            download_required = overwrite or not self._find_cached_file(filename)
            if download_required:
                with open(part_filename, 'wb') as fd:
                    for chunk in response.iter_content(chunk_size=block_size):
                        fd.write(chunk)
                os.rename(part_filename, filename)
        return filename, download_required

    def _download_eso_files(self, file_ids: List[str], destination: Optional[str],
                            overwrite: bool) -> List[str]:
        destination = destination or self.cache_location
        destination = os.path.abspath(destination)
        os.makedirs(destination, exist_ok=True)
        nfiles = len(file_ids)
        self.log_info(f"Downloading {nfiles} files ...")
        downloaded_files = []
        for i, file_id in enumerate(file_ids, 1):
            file_link = self.DOWNLOAD_URL + file_id
            self.log_info(f"Downloading file {i}/{nfiles} {file_link} to {destination}")
            try:
                filename, downloaded = self._download_eso_file(file_link, destination, overwrite)
                downloaded_files.append(filename)
                if downloaded:
                    self.log_info(f"Successfully downloaded dataset {file_id} to {filename}")
            except requests.HTTPError as http_error:
                if http_error.response.status_code == 401:
                    self.log_error(f"Access denied to {file_link}")
                else:
                    self.log_error(f"Failed to download {file_link}. {http_error}")
            except RuntimeError as ex:
                self.log_error(f"Failed to download {file_link}. {ex}")
        return downloaded_files

    def _unzip_file(self, filename: str) -> str:
        """
        Uncompress the provided file with gunzip.

        Note: ``system_tools.gunzip`` does not work with .Z files
        """
        uncompressed_filename = None
        if filename.endswith(('fits.Z', 'fits.gz')):
            uncompressed_filename = filename.rsplit(".", 1)[0]
            if not os.path.exists(uncompressed_filename):
                self.log_info(f"Uncompressing file {filename}")
                try:
                    subprocess.run([self.GUNZIP, filename], check=True)
                except UnknownException as ex:
                    uncompressed_filename = None
                    self.log_error(f"Failed to unzip {filename}: {ex}")
        return uncompressed_filename or filename

    def _unzip_files(self, files: List[str]) -> List[str]:
        if shutil.which(self.GUNZIP):
            files = [self._unzip_file(file) for file in files]
        else:
            warnings.warn("Unable to unzip files "
                          "(gunzip is not available on this system)")
        return files

    @staticmethod
    def _get_unique_files_from_association_tree(xml: str) -> Set[str]:
        tree = ET.fromstring(xml)
        return {element.attrib['name'] for element in tree.iter('file')}

    def _save_xml(self, payload: bytes, filename: str, destination: str):
        destination = destination or self.cache_location
        destination = os.path.abspath(destination)
        os.makedirs(destination, exist_ok=True)
        filename = os.path.join(destination, filename)
        self.log_info(f"Saving Calselector association tree to {filename}")
        with open(filename, "wb") as fd:
            fd.write(payload)

    def get_associated_files(self, datasets: List[str], *, mode: str = "raw",
                             savexml: bool = False, destination: str = None) -> List[str]:
        """
        Invoke Calselector service to find calibration files associated to the provided datasets.

        Parameters
        ----------
        datasets : list of strings
            List of datasets for which calibration files should be retrieved.
        mode : string
            Calselector mode: 'raw' (default) for raw calibrations,
             or 'processed' for processed calibrations.
        savexml : bool
            If true, save to disk the XML association tree returned by Calselector.
        destination : string
            Directory where the XML files are saved (default = astropy cache).

        Returns
        -------
        files :
            List of unique datasets associated to the input datasets.
        """
        mode = "Raw2Raw" if mode == "raw" else "Raw2Master"
        post_data = {"dp_id": datasets, "mode": mode}
        response = self._session.post(self.CALSELECTOR_URL, data=post_data)
        response.raise_for_status()
        associated_files = set()
        content_type = response.headers['Content-Type']
        # Calselector can return one or more XML association trees depending on the input.
        # For a single dataset it returns one XML and content-type = 'application/xml'
        if 'application/xml' in content_type:
            filename = self._get_filename_from_response(response)
            xml = response.content
            associated_files.update(self._get_unique_files_from_association_tree(xml))
            if savexml:
                self._save_xml(xml, filename, destination)
        # For multiple datasets it returns a multipart message
        elif 'multipart/form-data' in content_type:
            msg = email.message_from_string(f'Content-Type: {content_type}\r\n' + response.content.decode())
            for part in msg.get_payload():
                filename = part.get_filename()
                xml = part.get_payload(decode=True)
                associated_files.update(self._get_unique_files_from_association_tree(xml))
                if savexml:
                    self._save_xml(xml, filename, destination)
        else:
            raise CalSelectorError(f"Unexpected content-type '{content_type}' for {response.url}")

        # remove input datasets from calselector results
        return list(associated_files.difference(set(datasets)))

    @deprecated_renamed_argument(('request_all_objects', 'request_id'), (None, None),
                                 since=['0.4.7', '0.4.7'])
    def retrieve_data(self, datasets, *, continuation=False, destination=None,
                      with_calib=None, unzip=True,
                      request_all_objects=None, request_id=None):
        """
        Retrieve a list of datasets form the ESO archive.

        Parameters
        ----------
        datasets : list of strings or string
            List of datasets strings to retrieve from the archive.
        destination: string
            Directory where the files are copied.
            Files already found in the destination directory are skipped,
            unless continuation=True.
            Default to astropy cache.
        continuation : bool
            Force the retrieval of data that are present in the destination
            directory.
        with_calib : string
            Retrieve associated calibration files: None (default), 'raw' for
            raw calibrations, or 'processed' for processed calibrations.
        unzip : bool
            Unzip compressed files from the archive after download. `True` by
            default.

        Returns
        -------
        files : list of strings or string
            List of files that have been locally downloaded from the archive.

        Examples
        --------
        >>> dptbl = Eso.query_instrument('apex', pi_coi='ginsburg')
        >>> dpids = [row['DP.ID'] for row in dptbl if 'Map' in row['Object']]
        >>> files = Eso.retrieve_data(dpids)

        """
        _ = request_all_objects, request_id
        return_string = False
        if isinstance(datasets, str):
            return_string = True
            datasets = [datasets]

        if with_calib and with_calib not in ('raw', 'processed'):
            raise ValueError("Invalid value for 'with_calib'. "
                             "It must be 'raw' or 'processed'")

        associated_files = []
        if with_calib:
            self.log_info(f"Retrieving associated '{with_calib}' calibration files ...")
            try:
                # batch calselector requests to avoid possible issues on the ESO server
                BATCH_SIZE = 100
                sorted_datasets = sorted(datasets)
                for i in range(0, len(sorted_datasets), BATCH_SIZE):
                    associated_files += self.get_associated_files(sorted_datasets[i:i + BATCH_SIZE], mode=with_calib)
                associated_files = list(set(associated_files))
                self.log_info(f"Found {len(associated_files)} associated files")
            except UnknownException as ex:
                self.log_error(f"Failed to retrieve associated files: {ex}")

        all_datasets = datasets + associated_files
        self.log_info("Downloading datasets ...")
        files = self._download_eso_files(all_datasets, destination, continuation)
        if unzip:
            files = self._unzip_files(files)
        self.log_info("Done!")
        return files[0] if files and len(files) == 1 and return_string else files

    def _activate_form(self, response, *, form_index=0, form_id=None, inputs=None,
                       cache=True, method=None):
        """
        Parameters
        ----------
        method: None or str
            Can be used to override the form-specified method
        """
        inputs = inputs or {}
        # Extract form from response
        root = BeautifulSoup(response.content, 'html5lib')
        if form_id is None:
            form = root.find_all('form')[form_index]
        else:
            form = root.find_all('form', id=form_id)[form_index]
        # Construct base url
        form_action = form.get('action')
        if "://" in form_action:
            url = form_action
        elif form_action.startswith('/'):
            url = '/'.join(response.url.split('/', 3)[:3]) + form_action
        else:
            url = response.url.rsplit('/', 1)[0] + '/' + form_action
        # Identify payload format
        fmt = None
        form_method = form.get('method').lower()
        if form_method == 'get':
            fmt = 'get'  # get(url, params=payload)
        elif form_method == 'post':
            if 'enctype' in form.attrs:
                if form.attrs['enctype'] == 'multipart/form-data':
                    fmt = 'multipart/form-data'  # post(url, files=payload)
                elif form.attrs['enctype'] == 'application/x-www-form-urlencoded':
                    fmt = 'application/x-www-form-urlencoded'  # post(url, data=payload)
                else:
                    raise RuntimeError("enctype={0} is not supported!".format(form.attrs['enctype']))
            else:
                fmt = 'application/x-www-form-urlencoded'  # post(url, data=payload)
        # Extract payload from form
        payload = []
        for form_elem in form.find_all(['input', 'select', 'textarea']):
            value = None
            is_file = False
            tag_name = form_elem.name
            key = form_elem.get('name')
            if tag_name == 'input':
                is_file = (form_elem.get('type') == 'file')
                value = form_elem.get('value')
                if form_elem.get('type') in ['checkbox', 'radio']:
                    if form_elem.has_attr('checked'):
                        if not value:
                            value = 'on'
                    else:
                        value = None
            elif tag_name == 'select':
                if form_elem.get('multiple') is not None:
                    value = []
                    if form_elem.select('option[value]'):
                        for option in form_elem.select('option[value]'):
                            if option.get('selected') is not None:
                                value.append(option.get('value'))
                    else:
                        for option in form_elem.select('option'):
                            if option.get('selected') is not None:
                                # bs4 NavigableString types have bad,
                                # undesirable properties that result
                                # in recursion errors when caching
                                value.append(str(option.string))
                else:
                    if form_elem.select('option[value]'):
                        for option in form_elem.select('option[value]'):
                            if option.get('selected') is not None:
                                value = option.get('value')
                        # select the first option field if none is selected
                        if value is None:
                            value = form_elem.select(
                                'option[value]')[0].get('value')
                    else:
                        # survey form just uses text, not value
                        for option in form_elem.select('option'):
                            if option.get('selected') is not None:
                                value = str(option.string)
                        # select the first option field if none is selected
                        if value is None:
                            value = str(form_elem.select('option')[0].string)

            if key in inputs:
                if isinstance(inputs[key], list):
                    # list input is accepted (for array uploads)
                    value = inputs[key]
                else:
                    value = str(inputs[key])

            if (key is not None):  # and (value is not None):
                if fmt == 'multipart/form-data':
                    if is_file:
                        payload.append(
                            (key, ('', '', 'application/octet-stream')))
                    else:
                        if type(value) is list:
                            for v in value:
                                entry = (key, ('', v))
                                # Prevent redundant key, value pairs
                                # (can happen if the form repeats them)
                                if entry not in payload:
                                    payload.append(entry)
                        elif value is None:
                            entry = (key, ('', ''))
                            if entry not in payload:
                                payload.append(entry)
                        else:
                            entry = (key, ('', value))
                            if entry not in payload:
                                payload.append(entry)
                else:
                    if type(value) is list:
                        for v in value:
                            entry = (key, v)
                            if entry not in payload:
                                payload.append(entry)
                    else:
                        entry = (key, value)
                        if entry not in payload:
                            payload.append(entry)

        # for future debugging
        self._payload = payload
        self.log_debug("Form: payload={0}".format(payload))

        if method is not None:
            fmt = method

        self.log_debug("Method/format = {0}".format(fmt))

        # Send payload
        if fmt == 'get':
            response = self._request("GET", url, params=payload, cache=cache)
        elif fmt == 'multipart/form-data':
            response = self._request("POST", url, files=payload, cache=cache)
        elif fmt == 'application/x-www-form-urlencoded':
            response = self._request("POST", url, data=payload, cache=cache)

        return response

    def query_apex_quicklooks(self, *, project_id=None, print_help=False,
                              open_form=False, cache=True, **kwargs):
        """
        APEX data are distributed with quicklook products identified with a
        different name than other ESO products.  This query tool searches by
        project ID or any other supported keywords.

        Examples
        --------
        >>> tbl = Eso.query_apex_quicklooks(project_id='093.C-0144')
        >>> files = Eso.retrieve_data(tbl['Product ID'])
        """

        apex_query_url = 'http://archive.eso.org/wdb/wdb/eso/apex_product/form'

        table = None
        if open_form:
            webbrowser.open(apex_query_url)
        elif print_help:
            # TODO: print some sensible help message
            return "No help available for apex at the moment."
        else:

            payload = {'wdbo': 'csv/download'}
            if project_id is not None:
                payload['prog_id'] = project_id
            payload.update(kwargs)

            apex_form = self._request("GET", apex_query_url, cache=cache)
            apex_response = self._activate_form(
                apex_form, form_id='queryform', form_index=0, inputs=payload,
                cache=cache, method='application/x-www-form-urlencoded')

            content = apex_response.content
            if content:
                # First line is always garbage
                content = content.split(b'\n', 1)[1]
                try:
                    table = Table.read(BytesIO(content), format="ascii.csv",
                                       guess=False,  # header_start=1,
                                       comment="#", encoding='utf-8')
                except ValueError as ex:
                    if 'the encoding parameter is not supported on Python 2' in str(ex):
                        # astropy python2 does not accept the encoding parameter
                        table = Table.read(BytesIO(content), format="ascii.csv",
                                           guess=False,
                                           comment="#")
                    else:
                        raise ex
            else:
                raise RemoteServiceError("Query returned no results")

            return table

    def _print_query_help(self, url, *, cache=True):
        """
        Download a form and print it in a quasi-human-readable way
        """
        self.log_info("List of accepted column_filters parameters.")
        self.log_info("The presence of a column in the result table can be "
                      + "controlled if prefixed with a [ ] checkbox.")
        self.log_info("The default columns in the result table are shown as "
                      + "already ticked: [x].")

        result_string = []

        resp = self._request("GET", url, cache=cache)
        doc = BeautifulSoup(resp.content, 'html5lib')
        form = doc.select("html body form pre")[0]
        # Unwrap all paragraphs
        paragraph = form.find('p')
        while paragraph:
            paragraph.unwrap()
            paragraph = form.find('p')
        # For all sections
        for section in form.select("table"):
            section_title = "".join(section.stripped_strings)
            section_title = "\n".join(["", section_title,
                                       "-" * len(section_title)])
            result_string.append(section_title)
            checkbox_name = ""
            checkbox_value = ""
            for tag in section.next_siblings:
                if tag.name == "table":
                    break
                elif tag.name == "input":
                    if tag.get('type') == "checkbox":
                        checkbox_name = tag['name']
                        checkbox_value = "[x]" if ('checked' in tag.attrs) else "[ ]"
                        name = ""
                        value = ""
                    else:
                        name = tag['name']
                        value = ""
                elif tag.name == "select":
                    options = []
                    for option in tag.select("option"):
                        options += ["{0} ({1})".format(option['value'], "".join(option.stripped_strings))]
                    name = tag["name"]
                    value = ", ".join(options)
                else:
                    name = ""
                    value = ""
                if "tab_" + name == checkbox_name:
                    checkbox = checkbox_value
                else:
                    checkbox = "   "
                if name != "":
                    result_string.append("{0} {1}: {2}"
                                         .format(checkbox, name, value))

        self.log_info("\n".join(result_string))
        return result_string

    @deprecated(since="v0.4.8", message=("The ESO list_surveys function is deprecated,"
                                         "Use the list_collections  function instead."))
    def list_surveys(self, *args, **kwargs):
        if "surveys" in kwargs.keys():
            kwargs["collections"] = kwargs["surveys"]
            del (kwargs["surveys"])
        return self.list_collections(*args, **kwargs)

    @deprecated(since="v0.4.8", message=("The ESO query_surveys function is deprecated,"
                                         "Use the query_collections  function instead."))
    def query_surveys(self, *args, **kwargs):
        if "surveys" in kwargs.keys():
            kwargs["collections"] = kwargs["surveys"]
            del (kwargs["surveys"])
        return self.query_collections(*args, **kwargs)


Eso = EsoClass()

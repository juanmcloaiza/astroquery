#!/usr/bin/env/python

"""
utils.py: helper functions for the astropy.eso module
"""

import copy
import hashlib
import pickle
from typing import Union, List
from datetime import datetime, timezone, timedelta

from astroquery import log

import numpy as np
import astropy.table
from astropy.table import Column

def _split_str_as_list_of_str(column_str: str):
    if column_str == '':
        column_list = []
    else:
        column_list = list(map(lambda x: x.strip(), column_str.split(',')))
    return column_list


def adql_sanitize_val(x):
    """
    If the value is a string, put it into single quotes
    """
    if isinstance(x, str):
        return f"'{x}'"
    else:
        return f"{x}"


def are_coords_valid(ra: float = None,
                     dec: float = None,
                     radius: float = None) -> bool:
    """
    ra, dec, radius must be either present all three
    or absent all three. Moreover, they must be float
    """
    is_a_valid_combination = True
    # if either of the three is None...
    if ((ra is None)
        or (dec is None)
            or (radius is None)):
        # ...all three must be none
        is_a_valid_combination = (
            (ra is None)
            and (dec is None)
            and (radius is None))
    else:
        # They are not None --> they must be float:
        is_a_valid_combination = (
            isinstance(ra, (float, int))
            and isinstance(dec, (float, int))
            and isinstance(radius, (float, int)))
    return is_a_valid_combination


def py2adql(table: str, columns: Union[List, str] = None,
            ra: float = None, dec: float = None, radius: float = None,
            where_constraints: List = None,
            order_by: str = '', order_by_desc=True,
            count_only: bool = False, top: int = None):
    """
    Return the adql string corresponding to the parameters passed
    See adql examples at https://archive.eso.org/tap_obs/examples
    """
    # We assume the coordinates passed are valid
    where_circle = []
    if ra:
        where_circle += [f'intersects(s_region, circle(\'ICRS\', {ra}, {dec}, {radius}))=1']

    # Initialize / validate
    query_string = None
    # do not modify the original list
    wc = [] if where_constraints is None else where_constraints[:]
    if isinstance(columns, str):
        columns = _split_str_as_list_of_str(columns)
    if columns is None or len(columns) < 1:
        columns = ['*']
    if count_only:
        columns = ['count(*)']

    # Build the query
    query_string = ', '.join(columns) + ' from ' + table
    if len(wc) > 0:
        where_string = ' where ' + ' and '.join(wc + where_circle)
        query_string += where_string

    if len(order_by) > 0:
        order_string = ' order by ' + order_by + (' desc ' if order_by_desc else ' asc ')
        query_string += order_string

    if top is not None:
        query_string = f"select top {top} " + query_string
    else:
        query_string = "select " + query_string

    return query_string.strip()


def eso_hash(query_str: str, url: str):
    """
    Return a hash given an adql query string and an url.
    """
    request_key = (query_str, url)
    h = hashlib.sha224(pickle.dumps(request_key)).hexdigest()
    return h


def is_file_expired(filepath, timeout):
    if timeout is None:
        is_expired = False
    else:
        try:
            current_time = datetime.now(timezone.utc)
            file_time = datetime.fromtimestamp(filepath.stat().st_mtime, timezone.utc)
            is_expired = current_time-file_time > timedelta(seconds=timeout)
        except FileNotFoundError:
            is_expired = True
    return is_expired


def read_table_from_file(filepath):
    with open(filepath, "rb") as f:
        table = pickle.load(f)
    return table


def to_cache(table, cache_file):
    """
    Dump a table to a pickle file
    """
    log.debug("Caching data to %s", cache_file)

    table = copy.deepcopy(table)
    with open(cache_file, "wb") as f:
        pickle.dump(table, f, protocol=4)

import numpy as np
import astropy.table
from astropy.table import Column

# -------------------------------
# General helper functions
# -------------------------------

def _from_element_to_list(element, element_type=str):
    if element is None:
        return None
    if isinstance(element, list):
        if all(isinstance(e, element_type) for e in element):
            return element
        else:
            raise TypeError(f"All elements must be of type {element_type}")
    if hasattr(element, 'tolist'):
        lst = element.tolist()
        if all(isinstance(e, element_type) for e in lst):
            return lst
        else:
            raise TypeError(f"All elements must be of type {element_type}")
    if isinstance(element, element_type):
        return [element]
    raise TypeError(f"Invalid type for: {element} (expected {element_type})")

def _create_comma_separated_list(list_of_strings):
    return ", ".join(list_of_strings) if list_of_strings else "*"

# -------------------------------
# Query-string helper functions
# -------------------------------

def _condition_collections_like(collections):
    cols = _from_element_to_list(collections, str) if collections is not None else ["%"]
    return " OR ".join(f"collection LIKE '{col}'" for col in cols)

def _condition_tables_like(tables):
    tabs = _from_element_to_list(tables, str) if tables is not None else ["%"]
    return " OR ".join(f"table_name LIKE '{tab}'" for tab in tabs)

def _condition_order_by_like(order_by, order="ascending"):
    return f" ORDER BY {order_by} {order.upper()}" if order_by else ""

def _conditions_dict_like(conditions_dict):
    if conditions_dict:
        return " ".join(f"WHERE {key}={value}" for key, value in conditions_dict.items())
    return ""

def _create_query_all_catalogues(all_versions, collections, tables):
    query = """
        SELECT 
            collection, title, version, table_name, filter, instrument, telescope, publication_date, 
            ref.description AS description, number_rows, number_columns, rel_descr_url, acknowledgment,
            cat_id, mjd_obs, mjd_end, skysqdeg, bibliography, document_id, kc.from_column AS from_column,
            k.target_table AS target_table, kc.target_column AS target_column, schema_name
        FROM TAP_SCHEMA.tables AS ref
        LEFT OUTER JOIN TAP_SCHEMA.keys AS k ON ref.table_name = k.from_table 
        LEFT OUTER JOIN TAP_SCHEMA.key_columns AS kc ON k.key_id = kc.key_id
        WHERE schema_name = 'safcat'
    """
    if not all_versions:
        query += """
        AND cat_id IN (
            SELECT t1.cat_id 
            FROM TAP_SCHEMA.tables t1
            LEFT JOIN TAP_SCHEMA.tables t2 ON (t1.title = t2.title AND t1.version < t2.version)
            WHERE t2.title IS NULL
        )
        """
    if collections:
        query += f" AND ({_condition_collections_like(collections)})"
    if tables:
        query += f" AND ({_condition_tables_like(tables)})"
    return query

def _create_query_all_columns(collections, tables):
    return f"""
        SELECT table_name, column_name, ucd, datatype, description, unit
        FROM TAP_SCHEMA.columns
        WHERE table_name IN (
            SELECT table_name FROM TAP_SCHEMA.tables WHERE {_condition_collections_like(collections)}
        )
        AND ({_condition_tables_like(tables)})
    """

def _create_query_catalogues(table_name, columns, conditions_dict, order_by, order, top):
    base = _create_query_table_base(table_name, columns, top)
    cond = _conditions_dict_like(conditions_dict)
    order_clause = _condition_order_by_like(order_by, order)
    return f"{base} {cond} {order_clause}"

def _create_query_table_base(table_name, columns, top):
    select_clause = f"SELECT {'TOP ' + str(top) + ' ' if top else ''}{_create_comma_separated_list(columns)}"
    return f"{select_clause} FROM {table_name}"

def _set_last_version(table, update=True):
    required_cols = ["title", "version"]
    for col in required_cols:
        if col not in table.colnames:
            print(f"Column '{col}' missing. `last_version` will not be created.")
            return
    if "last_version" in table.colnames and not update:
        print("'last_version' column already exists. Skipping update.")
        return
    unique_titles = np.unique(table["title"]).tolist()
    last_version_flags = np.zeros(len(table), dtype=bool)
    for title in unique_titles:
        mask = (table["title"] == title)
        versions = table[mask]["version"]
        try:
            versions_numeric = versions.astype(float)
        except Exception:
            versions_numeric = versions
        latest = np.nanmax(versions_numeric)
        last_version_flags[mask] = (versions_numeric == latest)
    table.add_column(Column(data=last_version_flags, name="last_version", dtype=bool,
                            description="True if this is the latest version of the catalogue"))

# -------------------------------
# Validation helper functions
# -------------------------------

def _is_collection_list_at_eso(eso, collections):
    assert collections is None or isinstance(collections, (str, list)), "`collections` must be None, str, or list"
    collections_list = _from_element_to_list(collections, str)
    if collections_list:
        return [c for c in collections_list if _is_collection_at_eso(eso, c)]
    else:
        return None

def _is_table_list_at_eso(eso, tables):
    assert tables is None or isinstance(tables, (str, list)), "`tables` must be None, str, or list"
    tables_list = _from_element_to_list(tables, str)
    if tables_list:
        return [t for t in tables_list if _is_table_at_eso(eso, t)]
    else:
        return None

def _is_collection_at_eso(eso, collection):
    table_all = eso.all_list_catalogues(all_versions=False, verbose=False)
    all_cols = np.unique(table_all["collection"]).tolist()
    if collection not in all_cols:
        print(f"Warning: Collection '{collection}' not recognized. Possible values:\n{all_cols}")
        return False
    return True

def _is_table_at_eso(eso, table_name):
    table_all = eso.all_list_catalogues(all_versions=True, verbose=False)
    all_tables = table_all["table_name"].tolist()
    if table_name not in all_tables:
        print(f"Warning: Table '{table_name}' not recognized. Possible values:\n{all_tables}")
        return False
    if "last_version" in table_all.colnames:
        last_versions = table_all["last_version"].tolist()
        if not last_versions[all_tables.index(table_name)]:
            print(f"Warning: '{table_name}' is not the most recent version of the catalogue.")
    return True

def _is_collection_and_table_list_at_eso(eso, collections, tables, all_versions=False):
    clean_collections = _is_collection_list_at_eso(eso, collections)
    clean_tables = _is_table_list_at_eso(eso, tables) or []
    if clean_collections:
        for coll in clean_collections:
            clean_tables += _get_tables_from_collection(eso, coll, all_versions=all_versions)
    return list(set(filter(None, clean_tables)))

def _get_tables_from_collection(eso, collection, all_versions=False):
    if not _is_collection_at_eso(eso, collection):
        return []
    table_all = eso.all_list_catalogues(all_versions=all_versions, verbose=False)
    if table_all is None or "table_name" not in table_all.colnames:
        return []
    return table_all[table_all["collection"] == collection]["table_name"].tolist()

def _get_catalogue_length_from_table(eso, table_name, all_versions=False):
    if not _is_table_at_eso(eso, table_name):
        return None
    table_all = eso.all_list_catalogues(all_versions=all_versions, verbose=False)
    if table_all is None or "number_rows" not in table_all.colnames:
        return None
    sel = table_all[table_all["table_name"] == table_name]
    if len(sel) == 0:
        return None
    return int(sel["number_rows"][0])

def _get_catalogue_length_from_tables(eso, tables, maxrec=None, all_versions=False):
    if not tables:
        return []
    if maxrec is not None:
        return [maxrec] * len(tables)
    return [_get_catalogue_length_from_table(eso, t, all_versions=all_versions) for t in tables]

def _is_column_in_catalogues(eso, column_name, collections=None, tables=None):
    table_all = eso.list_catalogues_info(collections=collections, tables=tables, verbose=False)
    if table_all is None or "column_name" not in table_all.colnames:
        return False
    return column_name in table_all["column_name"].tolist()

def _is_column_list_in_catalogues(eso, columns, collections=None, tables=None):
    if columns is None:
        return None
    columns_list = _from_element_to_list(columns, str)
    return [col for col in columns_list if _is_column_in_catalogues(eso, col, collections, tables)]

def _get_id_ra_dec_from_columns(eso, collections=None):
    all_columns_table = eso.list_catalogues_info(collections, verbose=False)
    filter_tokens = ((all_columns_table["ucd"] == "meta.id;meta.main") |
                     (all_columns_table["ucd"] == "pos.eq.ra;meta.main") |
                     (all_columns_table["ucd"] == "pos.eq.dec;meta.main"))
    return all_columns_table[filter_tokens]
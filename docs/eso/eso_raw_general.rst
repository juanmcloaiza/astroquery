Query the ESO Archive for Raw Data (Generic)
============================================

In some cases, you may want to query the ESO Science Archive without targeting a specific instrument. This is what the :meth:`~astroquery.eso.EsoClass.query_main` method is designed for. It allows access to the global raw data table, which combines metadata across all instruments. Internally, this method queries the ``dbo.raw`` table via ESO's `TAP service <https://archive.eso.org/programmatic/#TAP>`_, which you could also access directly using ADQL with a simple statement like:

.. doctest-skip::
   SELECT * FROM dbo.raw

Functionally, :meth:`~astroquery.eso.EsoClass.query_main` works the same way as :meth:`~astroquery.eso.EsoClass.query_instrument`, except you don’t need to specify an instrument table name directly. You can still apply column filters, control the columns returned, and limit result counts.

This method is particularly useful for querying instruments that do not have a dedicated instrument-specific table. Examples include:

- e.g. ``feros``: legacy spectrographs
- e.g. ``APICAM``, ``MASCOT``: all-sky cameras or auxiliary systems

Inspecting available query options
----------------------------------

As before, we start by inspecting the available columns that can be queried with the following:

.. doctest-remote-data::

    >>> eso.query_main(help=True)
    INFO: 
    Columns present in the table dbo.raw:
        column_name     datatype    xtype     unit 
    ------------------- -------- ----------- ------
        access_estsize     long              kbyte
            access_url     char                   
          datalink_url     char                   
              date_obs     char                   
                   dec   double                deg
               dec_pnt   double                deg
                   ...
             tpl_start     char                   

    Number of records present in the table dbo.raw:
    34821254
    [astroquery.eso.core]

Querying with constraints
-------------------------

Now that we know which of the columns are available for queries, we can, for example, retrieving all-sky images from the ``APICAM`` instrument using the ``LUMINANCE`` filter, on a single night (i.e. 2019-04-26):

.. doctest-remote-data::

    >>> eso.maxrec = -1    # Return all results without truncation
    >>> table = eso.query_main(
    ...                     column_filters={
    ...                         "instrument": "APICAM",
    ...                         "filter_path": "LUMINANCE",
    ...                         "exp_start": "between '2019-04-26' and '2019-04-27'"})
    >>> print(len(table))
    215
    >>> table.colnames
    ['object', 'ra', 'dec', 'dp_id', 'date_obs', 'prog_id',
    'access_estsize', 'access_url', 'datalink_url', ... 'tpl_start']
    >>> table[["object", "ra", "dec", "date_obs", "prog_id"]]
     <Table length=215>
    object      ra          dec              date_obs          prog_id   
                deg          deg                                          
    object   float64      float64             object            object   
    ------- ------------ ------------ ----------------------- ------------
    ALL SKY 145.29212694 -24.53624194 2019-04-26T00:08:49.000 60.A-9008(A)
    ALL SKY 145.92251305 -24.53560305 2019-04-26T00:11:20.000 60.A-9008(A)
    ALL SKY    146.55707 -24.53497111 2019-04-26T00:13:52.000 60.A-9008(A)
    ...
    ALL SKY 143.56345694 -24.53804388 2019-04-26T23:57:59.000 60.A-9008(A)

**Note:** By default, the number of returned rows is limited to 1000. To retrieve more (or all) results, set:

.. doctest-remote-data::

    >>> eso.maxrec = -1  # disables the row limit entirely

You can also set ``eso.maxrec`` to a smaller/larger number to truncate/allow large queries.

.. _eso-reduced-data:

.. tip::

    Use ``query_main`` when you want to search **across all instruments**, for example to retrieve all observations of a specific source regardless of the instrument used.

    .. doctest-remote-data::

        table = eso.query_main(column_filters={"object": "NGC 3627"})

    Use ``query_instrument`` when you want a more **refined, instrument-specific search**, applying filters that are only available for a particular instrument (e.g. instrument modes, configurations, or ambient conditions).

    .. doctest-remote-data::

        column_filters = {
            "dp_cat": "SCIENCE",           # Science data only
            "ins_opt1_name": "HIGH_SENS",  # High sensitivity mode
            "night_flag": "night",         # Nighttime observations only
            "moon_illu": "< 0",            # No moon (below horizon)
            "lst": "between 0 and 6"       # Local sidereal time early in the night
        }

        table = eso.query_instrument("midi", column_filters=column_filters)
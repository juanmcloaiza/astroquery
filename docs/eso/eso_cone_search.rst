
******************
Simple Cone Search 
******************

Cone Search for Reduced Data
============================

This example demonstrates how to perform a basic **cone search** for publicly available **HAWK-I reduced data products** around the Galactic Center (Sgr A\*) using :meth:`~astroquery.eso.EsoClass.query_surveys`.

Sgr A\* is located at right ascension 266.41683° and declination –29.00781°. We perform a search within a 0.05-degree radius (~3 arcminutes).

.. doctest-remote-data::

    >> import astropy.units as u # import the astropy.units module

    >>> ra = 266.41683 *u.deg # degrees
    >>> dec = -29.00781 *u.deg # degrees
    >>> radius = 0.05 *u.deg # degrees

If coordinates are not known, you can use the :class:`~astropy.coordinates.SkyCoord` class to create them. Here, we create a SkyCoord object for Sgr A\*.

.. doctest-remote-data::

    >>> from astropy.coordinates import SkyCoord # import the SkyCoord class from the astropy.coordinates module
    >>> import astropy.units as u # import the astropy.units module

    >>> coords = SkyCoord.from_name("Sgr A*") 
    >>> ra = coords.ra
    >>> dec = coords.dec
    >>> radius = 0.05 *u.deg 

With the defined coordinates and radius, we can now perform the cone search using the `query_surveys` method of the `EsoClass`. This method allows us to filter results based on specific columns, such as `instrument_name`.

.. doctest-remote-data::

    >>> # Cone search
    >>> result = eso.query_surveys(
    ...        cone_ra=ra.value,
    ...        cone_dec=dec.value,
    ...        cone_radius=radius.to(u.deg).value,
    ...        column_filters={"instrument_name": "HAWKI"})

**Note**: The `cone_ra`, `cone_dec`, and `cone_radius` parameters are specified in degrees, but as float values (so we use `.value` to extract the float from the `astropy.units.Quantity`).

Cone Search for Raw Data
========================

Similar cone search functionality is also available through :meth:`~astroquery.eso.EsoClass.query_instrument` and :meth:`~astroquery.eso.EsoClass.query_main` by passing the same ``cone_ra``, ``cone_dec``, and ``cone_radius`` arguments. 

Instrument-Specific Cone Search
-------------------------------

Cone search for raw data products can be performed using the instrument-specific method, such as :meth:`~astroquery.eso.EsoClass.query_instrument`. This example searches for HAWK-I raw data products around the same coordinates as above.

.. doctest-remote-data::

    >>> result = eso.query_instrument(
    ...             "HAWKI",
    ...             cone_ra=ra,
    ...             cone_dec=dec,
    ...             cone_radius=radius)

Generic Cone Search
-------------------

Cone search for raw data products can also be performed using the more generic method, :meth:`~astroquery.eso.EsoClass.query_main`. This allows you to search across all instruments without specifying one, with the following example searching for HAWK-I raw data products around the same coordinates as above.

.. doctest-remote-data::

    >>> result = eso.query_main(
    ...             "HAWKI",
    ...             cone_ra=ra,
    ...             cone_dec=dec,
    ...             cone_radius=radius
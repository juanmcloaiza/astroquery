
Simple Cone Search 
==================

This example demonstrates how to perform a basic **cone search** for publicly available **HAWK-I Phase 3 (reduced) data products** around the Galactic Center (Sgr A\*) using :meth:`~astroquery.eso.EsoClass.query_surveys`.

Sgr A\* is located at right ascension 266.41683° and declination –29.00781°. We perform a search within a 0.05-degree radius (~3 arcminutes).

.. doctest-remote-data::

    >>> # Coordinates of Sgr A* (Galactic Center)
    >>> ra = 266.41683 # degrees
    >>> dec = -29.00781 # degrees
    >>> radius = 0.05  # degrees

    >>> # Cone search
    >>> result = eso.query_surveys(
    ...        cone_ra=ra,
    ...        cone_dec=dec,
    ...        cone_radius=radius
    ...        column_filters={"instrument_name": "HAWKI"})

Similar cone search functionality is also available through :meth:`~astroquery.eso.EsoClass.query_instrument` and :meth:`~astroquery.eso.EsoClass.query_main` by passing the same ``cone_ra``, ``cone_dec``, and ``cone_radius`` arguments. For example:

.. doctest-remote-data::

    >>> result = eso.query_instrument(
    ...             "HAWKI",
    ...             cone_ra=ra,
    ...             cone_dec=dec,
    ...             cone_radius=radius)

.. doctest-remote-data::

    >>> result = eso.query_main(
    ...             "HAWKI",
    ...             cone_ra=ra,
    ...             cone_dec=dec,
    ...             cone_radius=radius
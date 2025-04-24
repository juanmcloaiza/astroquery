"""
utils.py: helper functions for the astropy.eso module
"""

from typing import Dict, List, Optional, Union
from astropy.table import Table

DEFAULT_LEAD_COLS_RAW = ['object', 'ra', 'dec', 'dp_id', 'date_obs', 'prog_id']
DEFAULT_LEAD_COLS_PHASE3 = ['target_name', 's_ra', 's_dec', 'dp_id', 'date_obs', 'proposal_id']


def _split_str_as_list_of_str(column_str: str):
    if column_str == '':
        column_list = []
    else:
        column_list = list(map(lambda x: x.strip(), column_str.split(',')))
    return column_list


def raise_if_has_deprecated_keys(filters: Optional[Dict[str, str]]) -> bool:
    if not filters:
        return

    if any(k in filters for k in {"box", "coord1", "coord2"}):
        raise ValueError(
            "box, coord1 and coord2 are deprecated; "
            "use cone_ra, cone_dec and cone_radius instead"
        )

    if any(k in filters for k in {"etime", "stime"}):
        raise ValueError(
            "stime and etime are deprecated; "
            "use instead exp_time, together with '<', '>', 'between'\n"
            "Examples:\n"
            "\t column_filters = {'exp_time': '< 2024-01-01'}"
            "\t column_filters = {'exp_time': '> 2023-01-01'}"
            "\t column_filters = {'exp_time': between '2023-01-01' and '2024-01-01'}"
        )


def _format_allowed_values(column_name: str, allowed_values: Union[List[str], str]) -> str:
    if isinstance(allowed_values, str):
        allowed_values = _split_str_as_list_of_str(allowed_values)
    quoted_values = [f"'{v.strip()}'" for v in allowed_values]
    return f"{column_name} in ({', '.join(quoted_values)})"


def _build_adql_query(
        table_name: str,
        columns: Union[List, str],
        column_name: str,
        allowed_values: Union[List[str], str],
        filters: Dict[str, str],
        cone_ra: float,
        cone_dec: float,
        cone_radius: float,
        count_only: bool,
        top: int
) -> str:
    where_constraints = []

    if allowed_values:
        where_constraints.append(_format_allowed_values(column_name, allowed_values))

    where_constraints += [
        f"{k} {adql_sanitize_op_val(v)}" for k, v in filters.items()
    ]

    return py2adql(
        table=table_name,
        columns=columns,
        cone_ra=cone_ra,
        cone_dec=cone_dec,
        cone_radius=cone_radius,
        where_constraints=where_constraints,
        count_only=count_only,
        top=top
    )


def reorder_columns(table: Table,
                    leading_cols: Optional[List[str]] = None):
    """
    Reorders the columns of the pased table so that the
    colums given by the list leading_cols are first.
    If no leading cols are passed, it defaults to
    ['object', 'ra', 'dec', 'dp_id', 'date_obs']
    Returns a table with the columns reordered.
    """
    if not isinstance(table, Table):
        return table

    leading_cols = leading_cols or DEFAULT_LEAD_COLS_RAW
    first_cols = []
    last_cols = table.colnames[:]
    for x in leading_cols:
        if x in last_cols:
            last_cols.remove(x)
            first_cols.append(x)
    last_cols = first_cols + last_cols
    table = table[last_cols]
    return table


def adql_sanitize_op_val(op_val):
    """
    Expected input:
        "= 5", "< 3.14", "like '%John Doe%'", "in ('item1', 'item2')"
        or just string values like "ESO", "ALMA", "'ALMA'", "John Doe"

    Logic:
        returns "<operator> <value>" if operator is provided.
        Defaults to "= <value>" otherwise.
    """
    supported_operators = {"=", ">", "<", "<=", ">=", "!=", "like", "between", "in"}

    if not isinstance(op_val, str):
        return f"= {op_val}"

    op_val = op_val.strip()
    parts = op_val.split(" ", 1)

    if len(parts) == 2 and parts[0].lower() in supported_operators:
        operator, value = parts
        return f"{operator} {value}"

    # Default case: no operator. Assign "="
    value = op_val if (op_val.startswith("'") and op_val.endswith("'")) else f"'{op_val}'"
    return f"= {value}"


def raise_if_coords_not_valid(cone_ra: Optional[float] = None,
                              cone_dec: Optional[float] = None,
                              cone_radius: Optional[float] = None) -> bool:
    """
    ra, dec, radius must be either present all three
    or absent all three. Moreover, they must be float
    """
    are_all_none = (cone_ra is None) and (cone_dec is None) and (cone_radius is None)
    are_all_float = isinstance(cone_ra, (float, int)) and \
        isinstance(cone_dec, (float, int)) and \
        isinstance(cone_radius, (float, int))
    is_a_valid_combination = are_all_none or are_all_float
    if not is_a_valid_combination:
        raise ValueError(
            "Either all three (cone_ra, cone_dec, cone_radius) must be present or none.\n"
            "Values provided:\n"
            f"\tcone_ra = {cone_ra}, cone_dec = {cone_dec}, cone_radius = {cone_radius}"
        )


def py2adql(table: str, columns: Union[List, str] = None,
            cone_ra: float = None, cone_dec: float = None, cone_radius: float = None,
            where_constraints: List = None,
            order_by: str = '', order_by_desc=True,
            count_only: bool = False, top: int = None):
    """
    Return the adql string corresponding to the parameters passed
    See adql examples at https://archive.eso.org/tap_obs/examples
    """
    # We assume the coordinates passed are valid
    where_circle = []
    if cone_radius is not None:
        where_circle += [
            f'intersects(s_region, circle(\'ICRS\', {cone_ra}, {cone_dec}, {cone_radius}))=1']

    # Initialize / validate
    query_string = None
    # do not modify the original list
    wc = [] if where_constraints is None else where_constraints[:]
    wc += where_circle
    if isinstance(columns, str):
        columns = _split_str_as_list_of_str(columns)
    if columns is None or len(columns) < 1:
        columns = ['*']
    if count_only:
        columns = ['count(*)']

    # Build the query
    query_string = ', '.join(columns) + ' from ' + table
    if len(wc) > 0:
        where_string = ' where ' + ' and '.join(wc)
        query_string += where_string

    if len(order_by) > 0:
        order_string = ' order by ' + order_by + (' desc ' if order_by_desc else ' asc ')
        query_string += order_string

    if top is not None:
        query_string = f"select top {top} " + query_string
    else:
        query_string = "select " + query_string

    return query_string.strip()

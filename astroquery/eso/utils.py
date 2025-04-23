"""
utils.py: helper functions for the astropy.eso module
"""

from typing import Union, List, Optional
from astropy.table import Table

DEFAULT_LEAD_COLS_RAW = ['object', 'ra', 'dec', 'dp_id', 'date_obs', 'prog_id']
DEFAULT_LEAD_COLS_PHASE3 = ['target_name', 's_ra', 's_dec', 'dp_id', 'date_obs', 'proposal_id']


def _split_str_as_list_of_str(column_str: str):
    if column_str == '':
        column_list = []
    else:
        column_list = list(map(lambda x: x.strip(), column_str.split(',')))
    return column_list


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


def are_coords_valid(ra: Optional[float] = None,
                     dec: Optional[float] = None,
                     radius: Optional[float] = None) -> bool:
    """
    ra, dec, radius must be either present all three
    or absent all three. Moreover, they must be float
    """
    are_all_none = (ra is None) and (dec is None) and (radius is None)
    are_all_float = isinstance(ra, (float, int)) and \
        isinstance(dec, (float, int)) and \
        isinstance(radius, (float, int))
    is_a_valid_combination = are_all_none or are_all_float
    return is_a_valid_combination


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

"""All functions related to making a leaderboard string from a database query.

Making a leadeboard is process.
    1. Get query from database; query should be ranked.
    2. Call create_window(), where focus_index is the index in rows in which to focus.
    3. If you need to perform an operation across a column, here's how you do it.
        3a. Transpose the window with zip(*window), assign to column variables.
            ---> Zipping arrays will yield its transpose.
        3b. Do operations over columns.
        3c. Transpose back with zip e.g. zip(col1, col2, col3). Cast to list.
    4. Call generate(). Pass the window (entries), header, desired padding, etc.
    5. If needed, highlight a specifc index. If you wanted to highlight the focus from
       window, remember that create_window returns that index.
    6. The leaerboard now needs to be joined with newline to create full message.
"""


def create_window(rows: list, focus_index: int, size: int = 5):
    """Create a sub-list of a bigger list, creating a window with a certain size.

    If the focus index is on edges, will still return the correct size.

    Also returns the 'corrected focus' as the second value.
    """
    extends = (size - 1) // 2
    corrected_center = min(max(extends, focus_index), len(rows) - 1 - extends)

    if focus_index <= extends:  # focus too front
        corrected_focus = focus_index
    elif focus_index > len(rows) - 1 - extends:  # focus too end
        corrected_focus = focus_index - corrected_center
    else:  # just right
        corrected_focus = extends

    return (
        rows[corrected_center - extends : corrected_center + extends + 1],
        corrected_focus,
    )


def generate(
    entries: list,
    headers: list,
    align: list,
    *,
    fill: str = ".",
    spacing: int = 2,
    max_padding: list = [],
) -> list[list[str], list[int]]:
    """Format and return a text-based scoreboard with dynamic alignment.

    Returned is a list of strings. You will need to join with newline.
    Also returns calculated padding for any further transformation.

    rows: the format of [row1[col1, col2, col3], row2[col1, col2, col3], ...]
    header: a list of the names of columns header[col1, col2, col3]
    align: a list of how to pad e.g. <, ^, >
    fill: character used for filling
    spacing: always put fill (if applicable) padding between columns
    max_padding: the max padding a column can have, if 0, "infinite" for that col
    """
    max_padding = [x if x else 999 for x in max_padding]  # if pad 0, set 999
    padding = max_width(entries, headers, max_padding)

    header_format = "{val:{align}{pad}}"
    headers_s = f"{' ' * spacing}".join(
        header_format.format(val=headers[i], align=align[i], pad=padding[i])
        for i in range(len(padding))
    )

    rows_s = []
    form = "{val:{fill}{align}{pad}{comma}}"
    for row in range(len(entries)):
        row_raw = []
        for col in range(len(entries[row])):
            row_raw.append(
                form.format(
                    val=entries[row][col],
                    fill="" if row % 2 else fill,
                    align=align[col],
                    pad=padding[col],
                    comma="" if isinstance(entries[row][col], str) else ",",
                )
            )
        rows_s.append(f"{(' ' if row % 2 else fill) * spacing}".join(row_raw))

    return [headers_s, *rows_s], padding


def highlight_user(
    scoreboard: list[str],
    index: int,
    col1_padding: int,
    *,
    header: bool = True,
):
    """Modify IN PLACE the leaderboard  to add an @ at specified index.

    We do some disgusting string splicing. In order for this to work consistently, there
    needs to be some minmal padding. We will move column 1 of index to the right by
    1, and to do that, we need a little bit of padding so we don't cross over into
    column 2.
    """
    this_rank = scoreboard[index + int(header)][0:col1_padding]
    scoreboard[index + 1] = (
        "@" + this_rank + scoreboard[index + int(header)][col1_padding + 1 :]
    )
    return scoreboard


def max_width(
    entries: list[list], headers: list[str] = None, max_padding: list[int] = None
) -> list[int]:
    """Return the max length of strings per column.

    Also takes into account commas in large numbers and a header if given.

    entires is [row1[col1, col2], ...]
    """
    padding = []

    if not headers:
        headers = [""] * len(entries)

    if not max_padding:
        max_padding = [999] * len(headers)

    for col in range(len(entries[0])):
        if isinstance(entries[0][col], str):
            entire_col = list(entries[row][col] for row in range(len(entries)))
        else:  # is a number, take into account comma
            entire_col = list(f"{entries[row][col]:,}" for row in range(len(entries)))
        widest_val = len(sorted(entire_col, key=len)[-1])
        width = max(widest_val, len(headers[col]))
        width_trunc = min(width, max_padding[col])
        padding.append(width_trunc)

    return padding

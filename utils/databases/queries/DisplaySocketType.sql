SELECT
    Boards.display_socket,
    Boards.mikrobus_count
FROM
    Boards
WHERE
    Boards.uid == (SELECT
                    SelectedBoard.uid
                FROM
                    SelectedBoard
                LIMIT
                    1)
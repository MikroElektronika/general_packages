-- %1 = search text (empty = no text filter)
-- %2 = display socket type of the selected board (Boards.display_socket)
-- mikroBUS displays (Displays.display_socket = 'MIKROBUS_SOCKET') are offered for every
-- board with at least one mikroBUS slot, independent of the board's own display socket,
-- so a board can offer both TFT_SOCKET and MIKROBUS_SOCKET displays.
SELECT *,
    uid AS item_uid,
    (name) AS item_title
FROM Displays
WHERE (
        (
            (
                (Displays.display_socket == '%2')
                AND (Displays.display_socket != 'MIKROBUS_SOCKET')
            )
            OR (Displays.display_socket IS NULL)
            OR (Displays.display_socket == 'NO_DISPLAY')
        )
        AND (
            Displays.uid IN (
                SELECT SDKToDisplay.display_uid
                FROM SDKToDisplay
                WHERE SDKToDisplay.sdk_uid == (
                        SELECT SelectedSDK.uid
                        FROM SelectedSDK
                        LIMIT 1
                    )
            )
        )
        AND (
            (Displays.name LIKE '%%1%')
            OR (Displays.uid LIKE '%%1%')
        )
        AND (
            SELECT SelectedDevice.tft_socket
            FROM SelectedDevice
            WHERE SelectedDevice.tft_socket == 1
        )
    )
    OR (
        (Displays.display_socket == 'MIKROBUS_SOCKET')
        AND (
            IFNULL(
                (
                    SELECT Boards.mikrobus_count
                    FROM Boards
                    WHERE Boards.uid == (
                            SELECT SelectedBoard.uid
                            FROM SelectedBoard
                            LIMIT 1
                        )
                ),
                0
            ) > 0
        )
        AND (
            Displays.uid IN (
                SELECT SDKToDisplay.display_uid
                FROM SDKToDisplay
                WHERE SDKToDisplay.sdk_uid == (
                        SELECT SelectedSDK.uid
                        FROM SelectedSDK
                        LIMIT 1
                    )
            )
        )
        AND (
            (Displays.name LIKE '%%1%')
            OR (Displays.uid LIKE '%%1%')
        )
    )
    OR (
        (Displays.display_socket IS NULL)
        OR (Displays.display_socket == 'NO_DISPLAY')
    )
ORDER BY CASE
        WHEN Displays.uid = "NO_DISPLAY" THEN 1
        ELSE 2
    END,
    name DESC

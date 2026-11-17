-- Devices query (pure MCU list for devices-first setup flow)
-- Parameters:
--   %1 = 'DIP' for a DIP socket board (needs the SelectedBoard table), '' otherwise
--   %2 = search text
WITH device_pin_counts AS (
    SELECT
        dtp.device_uid,
        dtp.package_uid,
        CAST(
            SUBSTR(dtp.package_uid, 0, INSTR(dtp.package_uid, '/'))
            AS INTEGER
        ) AS pin_count
    FROM
        DeviceToPackage dtp
    WHERE
        dtp.rowid = (
            -- One package per device. On a DIP socket board (%1 = 'DIP'): the DIP package that fits one of
            -- the selected board's sockets, then any DIP package, then the first package. Otherwise the
            -- first package. Without this, a DIP board got e.g. 28/QFN and an empty _MSDK_DIP_SOCKET_TYPE_.
            SELECT
                dtp2.rowid
            FROM
                DeviceToPackage dtp2
                LEFT JOIN Packages pkg2 ON pkg2.uid = dtp2.package_uid
            WHERE
                dtp2.device_uid = dtp.device_uid
            ORDER BY
                CASE
                    WHEN '%1' = '' THEN 0
                    WHEN JSON_EXTRACT(pkg2.sdk_config, '$._MSDK_DIP_SOCKET_TYPE_') IN (
                        SELECT socket_uid FROM BoardToSocket
                        WHERE board_uid = (SELECT uid FROM SelectedBoard LIMIT 1)
                    ) THEN 0
                    WHEN dtp2.package_uid LIKE '%%1%' THEN 1
                    ELSE 2
                END,
                dtp2.rowid
            LIMIT 1
        )
)
SELECT
    Devices.*,
    Devices.uid AS item_uid,
    Devices.name AS item_title,
    device_pin_counts.package_uid AS package_uid,
    COALESCE(device_pin_counts.pin_count, 0) AS pin_count
FROM
    Devices
    LEFT JOIN device_pin_counts ON Devices.uid = device_pin_counts.device_uid
WHERE
    -- Exclude MCU-card wrapper entries (e.g. MCU_CARD_*, SIBRAIN_*), keep standalone MCU rows.
    Devices.uid NOT IN (
        SELECT uid
        FROM DeviceDetails
        WHERE is_mcu_card = 1
    )
    AND (
        (Devices.name LIKE '%%2%')
        OR (Devices.uid LIKE '%%2%')
        OR (Devices.vendor LIKE '%%2%')
        OR (Devices.family_uid LIKE '%%2%')
        OR (Devices.ram LIKE '%%2%')
        OR (CAST(CAST(Devices.ram AS INTEGER) / 1024 AS TEXT) LIKE '%%2%')
        OR (CAST(CAST(Devices.ram AS INTEGER) / 1024 / 1024 AS TEXT) LIKE '%%2%')
        OR (CAST(CAST(Devices.ram AS INTEGER) / 1024 / 1024 / 1024 AS TEXT) LIKE '%%2%')
        OR (Devices.flash LIKE '%%2%')
        OR (Devices.max_speed LIKE '%%2%')
        OR (
            CAST(
                COALESCE(device_pin_counts.pin_count, 0)
                AS TEXT
            ) LIKE '%%2%'
        )
    )
ORDER BY
    Devices.uid;

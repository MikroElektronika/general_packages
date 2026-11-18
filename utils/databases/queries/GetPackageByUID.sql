-- Package of a device. One row per package; callers take the first.
-- Parameters:
--   %1 = device uid
--   %2 = board uid (optional). On a DIP socket board the DIP package that fits one of the board's
--        sockets comes first, so the setup gets its _MSDK_DIP_SOCKET_TYPE_ (PIC18F2455 on PICDEM
--        Lab II: 28/SPDIP, not 28/SOIC). Without a board (%2 left as it is) the order is by
--        package uid, as before.
SELECT Devices.uid, DeviceToPackage.package_uid
FROM
    Devices
    LEFT JOIN DeviceToPackage ON Devices.uid == DeviceToPackage.device_uid
    LEFT JOIN Packages ON Packages.uid == DeviceToPackage.package_uid
WHERE
	Devices.uid == '%1'
ORDER BY
    CASE
        WHEN JSON_EXTRACT(Packages.sdk_config, '$._MSDK_DIP_SOCKET_TYPE_') IN (
            SELECT socket_uid FROM BoardToSocket WHERE board_uid = '%2'
        ) THEN 0
        ELSE 1
    END,
    DeviceToPackage.package_uid;

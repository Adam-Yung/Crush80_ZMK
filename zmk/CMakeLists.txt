if(CONFIG_USB_DC_B91 OR CONFIG_BT_HCI_B91)
  zephyr_include_directories(include)
endif()

add_subdirectory_ifdef(CONFIG_USB_DC_B91 drivers/usb)
add_subdirectory_ifdef(CONFIG_BT_HCI_B91 drivers/bluetooth)
add_subdirectory_ifdef(CONFIG_BATTERY_B91_ADC drivers/sensor)
add_subdirectory_ifdef(CONFIG_WDT_B91 drivers/watchdog)
add_subdirectory_ifdef(CONFIG_AW20216S drivers/led)

if(CONFIG_BT_HCI_B91)
  zephyr_link_libraries(${CMAKE_CURRENT_SOURCE_DIR}/lib/liblt_9518_zephyr.a)
endif()

if(CONFIG_BOOT_DIAG)
  zephyr_library_named(boot_diag)
  zephyr_library_sources(src/boot_diag.c)
endif()

if(CONFIG_IMG_MANAGER AND CONFIG_WDT_B91)
  zephyr_library_named(mcuboot_confirm)
  zephyr_library_sources(src/mcuboot_confirm.c)
endif()

if(CONFIG_POWEROFF)
  zephyr_library_named(poweroff_b91)
  zephyr_library_sources(src/poweroff.c)
endif()

if(CONFIG_FLASH_MGMT)
  zephyr_library_named(flash_mgmt)
  zephyr_library_sources(src/flash_mgmt.c)
endif()

if(CONFIG_USB_DC_B91 AND CONFIG_ZMK_USB)
  zephyr_library_named(usb_cdc_recover)
  zephyr_library_sources(src/usb_cdc_recover.c)
endif()

execute_process(
  COMMAND git describe --always --dirty
  WORKING_DIRECTORY ${ZEPHYR_BASE}/..
  OUTPUT_VARIABLE BUILD_GIT_VERSION
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
if(NOT BUILD_GIT_VERSION)
  set(BUILD_GIT_VERSION "unknown")
endif()
zephyr_compile_definitions(BUILD_GIT_VERSION="${BUILD_GIT_VERSION}")

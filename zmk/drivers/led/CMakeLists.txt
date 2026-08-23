# SPDX-License-Identifier: Apache-2.0

zephyr_library()
zephyr_library_sources(aw20216s.c)
zephyr_library_sources(crush80_rgb.c)
zephyr_library_include_directories(
  ${ZEPHYR_BASE}/../zmk-src/app/include
  ${CMAKE_CURRENT_SOURCE_DIR}/../../include
)

# Version checking for PROJ

set (PACKAGE_VERSION "9.3.0")
set (PACKAGE_VERSION_MAJOR "9")
set (PACKAGE_VERSION_MINOR "3")
set (PACKAGE_VERSION_PATCH "0")

# These variable definitions parallel those in PROJ's
# cmake/CMakeLists.txt.
if (MSVC)
  # For checking the compatibility of MSVC_TOOLSET_VERSION; see
  # https://docs.microsoft.com/en-us/cpp/porting/overview-of-potential-upgrade-issues-visual-cpp
  # Assume major version number is obtained by dropping the last decimal
  # digit.
  math (EXPR MSVC_TOOLSET_MAJOR "${MSVC_TOOLSET_VERSION}/10")
endif ()

if (NOT PACKAGE_FIND_NAME STREQUAL "PROJ")
  # Check package name (in particular, because of the way cmake finds
  # package config files, the capitalization could easily be "wrong").
  # This is necessary to ensure that the automatically generated
  # variables, e.g., <package>_FOUND, are consistently spelled.
  set (REASON "package = PROJ, NOT ${PACKAGE_FIND_NAME}")
  set (PACKAGE_VERSION_UNSUITABLE TRUE)
elseif (NOT (APPLE OR (NOT DEFINED CMAKE_SIZEOF_VOID_P) OR
      CMAKE_SIZEOF_VOID_P EQUAL "8"))
  # Reject if there's a 32-bit/64-bit mismatch (not necessary with Apple
  # since a multi-architecture library is built for that platform).
  set (REASON "sizeof(*void) = 8")
  set (PACKAGE_VERSION_UNSUITABLE TRUE)
elseif (PACKAGE_FIND_VERSION)
  if (PACKAGE_FIND_VERSION VERSION_EQUAL PACKAGE_VERSION)
    set (PACKAGE_VERSION_EXACT TRUE)
  elseif (PACKAGE_FIND_VERSION VERSION_LESS PACKAGE_VERSION
    AND PACKAGE_FIND_VERSION_MAJOR EQUAL PACKAGE_VERSION_MAJOR)
    set (PACKAGE_VERSION_COMPATIBLE TRUE)
  endif ()
endif ()

# If unsuitable, append the reason to the package version so that it's
# visible to the user.
if (PACKAGE_VERSION_UNSUITABLE)
  set (PACKAGE_VERSION "${PACKAGE_VERSION} (${REASON})")
endif ()

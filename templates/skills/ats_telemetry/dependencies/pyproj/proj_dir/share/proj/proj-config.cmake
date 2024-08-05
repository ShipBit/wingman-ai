# Configure PROJ
#
# Set
#  PROJ_FOUND = 1
#  PROJ_INCLUDE_DIRS = /usr/local/include
#  PROJ_LIBRARIES = PROJ::proj
#  PROJ_LIBRARY_DIRS = /usr/local/lib
#  PROJ_BINARY_DIRS = /usr/local/bin
#  PROJ_VERSION = 4.9.1 (for example)
if(PROJ STREQUAL "PROJ4")
  message(DEPRECATION "find_package(PROJ4) is deprecated and will be retired soon. Please use find_package(PROJ) instead.")
endif()

include(CMakeFindDependencyMacro)

# We cannot have a find_dependency() call between cmake_policy(PUSH)/cmake_policy(POP)
# because find_dependency() issues a return() on failure, which results in
# imbalanced push/pop
# Cf https://gitlab.kitware.com/cmake/cmake/-/issues/17612
cmake_policy(PUSH)
cmake_policy(SET CMP0012 NEW)
if("ON")
    set(PROJ_CONFIG_FIND_TIFF_DEP ON)
endif()
if("TRUE")
    set(PROJ_CONFIG_FIND_CURL_DEP ON)
endif()
cmake_policy(POP)

find_dependency(unofficial-sqlite3 CONFIG)
if(DEFINED PROJ_CONFIG_FIND_TIFF_DEP)
    find_dependency(TIFF)
endif()

if(DEFINED PROJ_CONFIG_FIND_CURL_DEP)
  # Chainload CURL usage requirements
  find_dependency(CURL)
  # Target CURL::libcurl only defined since CMake 3.12
  if(NOT TARGET CURL::libcurl)
      add_library(CURL::libcurl INTERFACE IMPORTED)
      set_target_properties(CURL::libcurl PROPERTIES
        INTERFACE_INCLUDE_DIRECTORIES "${CURL_INCLUDE_DIRS}"
        INTERFACE_LINK_LIBRARIES      "${CURL_LIBRARIES}"
      )
  endif()
endif()

function(set_variable_from_rel_or_absolute_path var root rel_or_abs_path)
  if(IS_ABSOLUTE "${rel_or_abs_path}")
    set(${var} "${rel_or_abs_path}" PARENT_SCOPE)
  else()
    set(${var} "${root}/${rel_or_abs_path}" PARENT_SCOPE)
  endif()
endfunction()

# Tell the user project where to find our headers and libraries
get_filename_component (_DIR ${CMAKE_CURRENT_LIST_FILE} PATH)
get_filename_component (_ROOT "${_DIR}/../../../" ABSOLUTE)
# Use _ROOT as prefix here for the possibility of relocation after installation.
set_variable_from_rel_or_absolute_path("PROJ_INCLUDE_DIRS" "${_ROOT}" "include")
set_variable_from_rel_or_absolute_path("PROJ_LIBRARY_DIRS" "${_ROOT}" "lib")
set_variable_from_rel_or_absolute_path("PROJ_BINARY_DIRS" "${_ROOT}" "bin")

set (PROJ_LIBRARIES PROJ::proj)
# Read in the exported definition of the library
include ("${_DIR}/proj-targets.cmake")
if (ON)
  include ("${_DIR}/proj4-targets.cmake")
endif()

unset (_ROOT)
unset (_DIR)

if ("PROJ" STREQUAL "PROJ4")
  # For backward compatibility with old releases of libgeotiff
  set (PROJ_INCLUDE_DIR
    ${PROJ_INCLUDE_DIRS})
endif ()

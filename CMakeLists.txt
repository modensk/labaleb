cmake_minimum_required(VERSION 3.20)
project(labaleb LANGUAGES CXX)

# --- Target: 32-bit Source SDK 2013 (hl2.exe is x86) ---------------------------
# Configure with the Win32 generator, e.g.:
#   cmake -B build -A Win32
#   cmake --build build --config Release
if(NOT WIN32)
    message(WARNING "labaleb targets Windows/x86 (hl2.exe). Building on a non-Windows host will not produce a usable DLL.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- Dependencies --------------------------------------------------------------
# MinHook for function hooking (wired up from the bhop milestone onward).
include(FetchContent)
FetchContent_Declare(
    minhook
    GIT_REPOSITORY https://github.com/TsudaKageyu/minhook.git
    GIT_TAG        master
)
FetchContent_MakeAvailable(minhook)

# --- The cheat DLL -------------------------------------------------------------
file(GLOB_RECURSE LABALEB_SOURCES CONFIGURE_DEPENDS "${CMAKE_SOURCE_DIR}/src/*.cpp")

add_library(labaleb SHARED ${LABALEB_SOURCES})

target_include_directories(labaleb PRIVATE "${CMAKE_SOURCE_DIR}/src")
target_link_libraries(labaleb PRIVATE minhook)

# Source SDK 2013 is built with the multithreaded runtime; match it.
set_property(TARGET labaleb PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

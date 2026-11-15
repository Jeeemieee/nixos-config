cmake_minimum_required(VERSION 3.25)
project(workers-watch LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(SANITIZE "Build with the address and undefined-behaviour sanitizers, for the tests" OFF)
set(STATUS_COMMAND "" CACHE STRING "The command that prints the status document: a list, first an absolute path")

find_package(ftxui REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(Threads REQUIRED)

# The command becomes a fixed list of strings in the program: it is never read from a file, the environment or a document
set(statusCommandItems "")
foreach(part IN LISTS STATUS_COMMAND)
  if(part MATCHES "[\"\\\\\n]")
    message(FATAL_ERROR "STATUS_COMMAND: no quotation mark, backslash or line break is allowed in '${part}'")
  endif()
  string(APPEND statusCommandItems "\"${part}\", ")
endforeach()
if(STATUS_COMMAND AND NOT STATUS_COMMAND MATCHES "^/")
  message(FATAL_ERROR "STATUS_COMMAND must start with an absolute path, since no shell and no PATH look it up")
endif()
if(STATUS_COMMAND)
  set(statusCommandGiven 1)
else()
  set(statusCommandGiven 0)
endif()
configure_file(src/statusCommand.hpp.in statusCommand.hpp @ONLY)

add_executable(workers-watch
  src/main.cpp
  src/model.cpp
  src/source.cpp
  src/text.cpp
  src/view.cpp
)
target_include_directories(workers-watch PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(workers-watch PRIVATE
  ftxui::component ftxui::dom ftxui::screen
  nlohmann_json::nlohmann_json
  Threads::Threads
)

# Warnings are errors: this program shows text that agents wrote
target_compile_options(workers-watch PRIVATE
  -Wall -Wextra -Wpedantic -Werror
  -Wconversion -Wsign-conversion -Wshadow -Wformat=2 -Wold-style-cast
  -Wnon-virtual-dtor -Wcast-align -Wimplicit-fallthrough -Wundef
)

if(SANITIZE)
  target_compile_options(workers-watch PRIVATE
    -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all)
  target_link_options(workers-watch PRIVATE -fsanitize=address,undefined)
else()
  # The usual hardening, in addition to what the Nix compiler wrapper sets (fortify, relro, bindnow, pie)
  target_compile_definitions(workers-watch PRIVATE _GLIBCXX_ASSERTIONS)
  target_compile_options(workers-watch PRIVATE
    -fstack-protector-strong -fstack-clash-protection -fcf-protection=full)
  target_link_options(workers-watch PRIVATE -pie -Wl,-z,relro,-z,now,-z,noexecstack)
endif()

install(TARGETS workers-watch)

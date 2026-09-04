function(_toolbox_make_rule_name out_var base_name)
    set(options "")
    set(oneValueArgs TARGET)
    set(multiValueArgs "")
    cmake_parse_arguments(ARG "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    set(rule_name "${base_name}")
    if (ARG_TARGET)
        string(MAKE_C_IDENTIFIER "${ARG_TARGET}" target_id)
        string(APPEND rule_name "_${target_id}")
    endif ()

    set(${out_var} "${rule_name}" PARENT_SCOPE)
endfunction()

function(_toolbox_add_dependency_if_target target dependency)
    if (target)
        add_dependencies(${target} ${dependency})
    endif ()
endfunction()

function(_toolbox_add_command_target)
    set(options "")
    set(oneValueArgs NAME COMMENT WORKING_DIRECTORY DEPENDS_ON)
    set(multiValueArgs COMMAND)
    cmake_parse_arguments(ARG "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if (NOT ARG_NAME OR NOT ARG_COMMENT OR NOT ARG_COMMAND)
        message(FATAL_ERROR "_toolbox_add_command_target requires NAME, COMMENT, and COMMAND.")
    endif ()

    if (ARG_WORKING_DIRECTORY)
        add_custom_target(${ARG_NAME}
                COMMAND ${ARG_COMMAND}
                COMMENT "${ARG_COMMENT}"
                WORKING_DIRECTORY "${ARG_WORKING_DIRECTORY}"
                VERBATIM
        )
    else ()
        add_custom_target(${ARG_NAME}
                COMMAND ${ARG_COMMAND}
                COMMENT "${ARG_COMMENT}"
                VERBATIM
        )
    endif ()

    _toolbox_add_dependency_if_target("${ARG_DEPENDS_ON}" ${ARG_NAME})
endfunction()

function(enforce_copyright)
    set(options CHECK FIX)
    set(oneValueArgs CONFIG_FILE SOURCE_DIR TARGET)
    set(multiValueArgs "")
    cmake_parse_arguments(ARG "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if (NOT ARG_CONFIG_FILE OR NOT ARG_SOURCE_DIR)
        message(FATAL_ERROR "enforce_copyright requires CONFIG_FILE and SOURCE_DIR.")
    endif ()

    if (ARG_CHECK AND ARG_FIX)
        message(FATAL_ERROR "enforce_copyright accepts only one of CHECK or FIX.")
    endif ()

    find_program(UVX_EXECUTABLE NAMES uvx REQUIRED)
    get_filename_component(
            _toolbox_package
            "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/.."
            ABSOLUTE
    )

    set(_mode_args "")
    if (ARG_CHECK)
        list(APPEND _mode_args --check)
    elseif (ARG_FIX)
        list(APPEND _mode_args --fix)
    endif ()

    _toolbox_make_rule_name(_rule_name "enforce_copyright" TARGET "${ARG_TARGET}")
    _toolbox_add_command_target(
            NAME ${_rule_name}
            COMMENT "Syncing copyright headers with Git history"
            WORKING_DIRECTORY "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/.."
            COMMAND "${UVX_EXECUTABLE}"
                    --from "${_toolbox_package}"
                    toolbox-copyright
                    --config "${ARG_CONFIG_FILE}"
                    --directory "${ARG_SOURCE_DIR}"
                    ${_mode_args}
            DEPENDS_ON "${ARG_TARGET}"
    )
endfunction()

function(enforce_clang_format)
    set(options "")
    set(oneValueArgs TARGET)
    set(multiValueArgs FILES)
    cmake_parse_arguments(ARG "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if (NOT ARG_TARGET)
        message(FATAL_ERROR "enforce_clang_format requires TARGET.")
    endif ()

    if (NOT ARG_FILES)
        message(FATAL_ERROR "enforce_clang_format requires FILES.")
    endif ()

    find_program(CLANG_FORMAT_EXE clang-format REQUIRED)

    _toolbox_make_rule_name(_rule_name "enforce_clang_format" TARGET "${ARG_TARGET}")
    _toolbox_add_command_target(
            NAME ${_rule_name}
            COMMENT "Running clang-format on files"
            COMMAND "${CLANG_FORMAT_EXE}" -i ${ARG_FILES}
            DEPENDS_ON "${ARG_TARGET}"
    )
endfunction()

function(generate_clangd_compdb)
    set(options "")
    set(oneValueArgs TARGET DEST_DIR)
    set(multiValueArgs "")
    cmake_parse_arguments(ARG "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if (NOT ARG_TARGET OR NOT ARG_DEST_DIR)
        message(FATAL_ERROR "generate_clangd_compdb requires TARGET and DEST_DIR.")
    endif ()

    add_custom_command(TARGET ${ARG_TARGET} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${CMAKE_BINARY_DIR}/compile_commands.json
            ${ARG_DEST_DIR}/compile_commands.json
            COMMENT "Copying compile_commands.json to ${ARG_DEST_DIR}/compile_commands.json"
            VERBATIM
    )
endfunction()

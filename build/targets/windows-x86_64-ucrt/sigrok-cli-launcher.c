#define UNICODE
#define _UNICODE
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

#include "sigrok-cli-launcher-id.h"

#define PAYLOAD_RESOURCE 101
#define PATH_CAPACITY 32768

static int fail(const wchar_t *message)
{
	fwprintf(stderr, L"SLogic sigrok-cli launcher: %ls (error %lu)\n",
		message, GetLastError());
	return 125;
}

static BOOL append_path(wchar_t *path, const wchar_t *component)
{
	size_t length = wcslen(path);
	size_t component_length = wcslen(component);

	if (length && path[length - 1] != L'\\') {
		if (length + 1 >= PATH_CAPACITY)
			return FALSE;
		path[length++] = L'\\';
		path[length] = L'\0';
	}
	if (length + component_length >= PATH_CAPACITY)
		return FALSE;
	wmemcpy(path + length, component, component_length + 1);
	return TRUE;
}

static BOOL write_resource(const wchar_t *path)
{
	HRSRC resource = FindResourceW(NULL, MAKEINTRESOURCEW(PAYLOAD_RESOURCE), RT_RCDATA);
	HGLOBAL loaded;
	const void *data;
	DWORD size;
	HANDLE file;
	DWORD written;

	if (!resource)
		return FALSE;
	loaded = LoadResource(NULL, resource);
	if (!loaded)
		return FALSE;
	data = LockResource(loaded);
	size = SizeofResource(NULL, resource);
	if (!data || !size)
		return FALSE;

	file = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
		FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_TEMPORARY, NULL);
	if (file == INVALID_HANDLE_VALUE)
		return FALSE;
	if (!WriteFile(file, data, size, &written, NULL) || written != size) {
		CloseHandle(file);
		return FALSE;
	}
	return CloseHandle(file);
}

static DWORD run_process(const wchar_t *application, wchar_t *command_line,
	BOOL inherit_handles, DWORD creation_flags)
{
	STARTUPINFOW startup = { .cb = sizeof(startup) };
	PROCESS_INFORMATION process;
	DWORD exit_code = 125;

	if (!CreateProcessW(application, command_line, NULL, NULL, inherit_handles,
		creation_flags, NULL, NULL, &startup, &process))
		return 125;
	WaitForSingleObject(process.hProcess, INFINITE);
	GetExitCodeProcess(process.hProcess, &exit_code);
	CloseHandle(process.hThread);
	CloseHandle(process.hProcess);
	return exit_code;
}

static const wchar_t *command_line_arguments(void)
{
	const wchar_t *cursor = GetCommandLineW();

	if (*cursor == L'\"') {
		cursor++;
		while (*cursor && *cursor != L'\"')
			cursor++;
		if (*cursor == L'\"')
			cursor++;
	} else {
		while (*cursor && *cursor != L' ' && *cursor != L'\t')
			cursor++;
	}
	return cursor;
}

int wmain(void)
{
	wchar_t cache_root[PATH_CAPACITY];
	wchar_t payload_path[PATH_CAPACITY];
	wchar_t marker_path[PATH_CAPACITY];
	wchar_t cli_path[PATH_CAPACITY];
	wchar_t bin_path[PATH_CAPACITY];
	wchar_t decoder_path[PATH_CAPACITY];
	wchar_t mutex_name[256];
	wchar_t *extract_command = NULL;
	wchar_t *cli_command = NULL;
	wchar_t *old_path = NULL;
	wchar_t *new_path = NULL;
	HANDLE mutex = NULL;
	HANDLE marker;
	DWORD result = 125;
	DWORD old_path_length;
	const wchar_t *arguments;
	size_t command_length;

	if (!GetTempPathW(PATH_CAPACITY, cache_root))
		return fail(L"cannot locate the temporary directory");
	if (!append_path(cache_root, L"SLogic"))
		return fail(L"temporary path is too long");
	CreateDirectoryW(cache_root, NULL);
	if (!append_path(cache_root, L"sigrok-cli-" PAYLOAD_ID))
		return fail(L"cache path is too long");
	CreateDirectoryW(cache_root, NULL);

	swprintf(mutex_name, sizeof(mutex_name) / sizeof(mutex_name[0]),
		L"Local\\SLogic-sigrok-cli-%ls", PAYLOAD_ID);
	mutex = CreateMutexW(NULL, FALSE, mutex_name);
	if (!mutex || WaitForSingleObject(mutex, INFINITE) != WAIT_OBJECT_0)
		return fail(L"cannot lock the extraction cache");

	wcscpy(payload_path, cache_root);
	wcscpy(marker_path, cache_root);
	if (!append_path(payload_path, L"payload.exe") ||
		!append_path(marker_path, L".ready")) {
		result = fail(L"payload path is too long");
		goto unlock;
	}

	marker = CreateFileW(marker_path, GENERIC_READ, FILE_SHARE_READ, NULL,
		OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
	if (marker == INVALID_HANDLE_VALUE) {
		if (!write_resource(payload_path)) {
			result = fail(L"cannot write the embedded payload");
			goto unlock;
		}
		command_length = wcslen(payload_path) * 2 + wcslen(cache_root) + 32;
		extract_command = calloc(command_length, sizeof(wchar_t));
		if (!extract_command) {
			result = fail(L"out of memory");
			goto unlock;
		}
		swprintf(extract_command, command_length,
			L"\"%ls\" -y -o\"%ls\"", payload_path, cache_root);
		result = run_process(payload_path, extract_command, FALSE, CREATE_NO_WINDOW);
		if (result != 0) {
			fwprintf(stderr,
				L"SLogic sigrok-cli launcher: extraction failed (exit %lu)\n",
				result);
			goto unlock;
		}
		marker = CreateFileW(marker_path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
			CREATE_ALWAYS, FILE_ATTRIBUTE_HIDDEN, NULL);
		if (marker == INVALID_HANDLE_VALUE) {
			result = fail(L"cannot mark the extraction cache ready");
			goto unlock;
		}
	}
	CloseHandle(marker);

	ReleaseMutex(mutex);
	CloseHandle(mutex);
	mutex = NULL;

	wcscpy(bin_path, cache_root);
	wcscpy(cli_path, cache_root);
	wcscpy(decoder_path, cache_root);
	if (!append_path(bin_path, L"bin") ||
		!append_path(cli_path, L"bin\\sigrok-cli.exe") ||
		!append_path(decoder_path, L"share\\libsigrokdecode\\decoders"))
		return fail(L"runtime path is too long");

	old_path_length = GetEnvironmentVariableW(L"PATH", NULL, 0);
	old_path = calloc(old_path_length + 1, sizeof(wchar_t));
	new_path = calloc(wcslen(bin_path) + old_path_length + 2, sizeof(wchar_t));
	if (!old_path || !new_path)
		return fail(L"out of memory");
	if (old_path_length)
		GetEnvironmentVariableW(L"PATH", old_path, old_path_length + 1);
	swprintf(new_path, wcslen(bin_path) + old_path_length + 2,
		L"%ls;%ls", bin_path, old_path);
	SetEnvironmentVariableW(L"PATH", new_path);
	SetEnvironmentVariableW(L"PYTHONHOME", cache_root);
	SetEnvironmentVariableW(L"SIGROKDECODE_DIR", decoder_path);

	arguments = command_line_arguments();
	command_length = wcslen(cli_path) + wcslen(arguments) + 4;
	cli_command = calloc(command_length, sizeof(wchar_t));
	if (!cli_command)
		return fail(L"out of memory");
	swprintf(cli_command, command_length, L"\"%ls\"%ls", cli_path, arguments);
	result = run_process(cli_path, cli_command, TRUE, 0);
	if (result == 125 && GetLastError())
		fail(L"cannot start sigrok-cli");

	free(cli_command);
	free(new_path);
	free(old_path);
	free(extract_command);
	return (int)result;

unlock:
	if (mutex) {
		ReleaseMutex(mutex);
		CloseHandle(mutex);
	}
	free(extract_command);
	return (int)result;
}

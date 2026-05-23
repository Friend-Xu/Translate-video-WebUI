@echo off
echo === BAT Start ===
D:\Workspace\Translate_video\.venv\Scripts\python.exe --version
echo ---
D:\Workspace\Translate_video\.venv\Scripts\python.exe -c "print('hello')"
echo ---
D:\Workspace\Translate_video\.venv\Scripts\python.exe -c "open(r'D:\Workspace\Translate_video\tests\_bat_test.txt', 'w').write('ok'); print('file written')"
echo ---
type D:\Workspace\Translate_video\tests\_bat_test.txt 2>nul || echo FILE_NOT_FOUND
echo === BAT End ===

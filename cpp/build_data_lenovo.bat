@echo off
REM ===========================================================================
REM civulator_core build against the conda `data` env on ERIK_LENOVO.
REM Same toolchain pattern as breach's cpp/build_cpu_data.bat (Ninja + MSVC
REM vcvars64, pybind11 from the data env). Per-machine paths — adjust on
REM another PC. The pyd is staged into cpp/build/Release, where the package's
REM sys.path insert finds it.
REM ===========================================================================
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>nul
if not exist "%VCINSTALLDIR%" call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>nul
where cl
set "PYEXE=C:/Users/steen/miniconda3/envs/data/python.exe"
set "PYBIND=C:/Users/steen/miniconda3/envs/data/Lib/site-packages/pybind11/share/cmake/pybind11"
set "CMAKE=C:/Users/steen/miniconda3/envs/data/Scripts/cmake.exe"
set "NINJA=C:/Users/steen/miniconda3/envs/data/Scripts/ninja.exe"
cd /d "%~dp0\.."
echo === CONFIGURE (cpp/build, Ninja) ===
"%CMAKE%" -S cpp -B cpp/build -G Ninja ^
  -DCMAKE_MAKE_PROGRAM="%NINJA%" ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DPython_EXECUTABLE=%PYEXE% ^
  -DPYTHON_EXECUTABLE=%PYEXE% ^
  -Dpybind11_DIR=%PYBIND%
echo CONFIGURE_EXIT=%errorlevel%
echo === BUILD ===
"%CMAKE%" --build cpp/build
echo BUILD_EXIT=%errorlevel%
echo === STAGE into cpp/build/Release ===
if not exist "cpp\build\Release" mkdir "cpp\build\Release"
copy /Y "cpp\build\civulator_core*.pyd" "cpp\build\Release\" >nul
echo STAGE_EXIT=%errorlevel%
endlocal

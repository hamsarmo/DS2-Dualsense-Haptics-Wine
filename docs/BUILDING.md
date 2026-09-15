# Source, build and release

## Provenance

The released mmdevapi.dll was built from CodeWeavers' CrossOver **26.3.0** source
archive, not a different upstream Wine release. The archive's Wine version is
11.0. Installed CrossOver was 26.3.0.39832, source tag cxoffice-26.3.0rc2. The
archive itself does not carry the build serial; runtime compatibility was
verified with that installed build.

The download directory supplies `wine-crossover-26.3.0-source.tar.gz` as
corresponding source. This is the complete, unmodified `sources/wine/` subtree
extracted from the original CodeWeavers archive (unrelated projects omitted).
Our patch is supplied separately in this repository. Original archive provenance:

- Original URL: https://media.codeweavers.com/pub/crossover/source/crossover-sources-26.3.0.tar.gz
- SHA-256: `ac99c8ca4b3848f3e81784135f023df266b61c2345726ea55a50b3e030dd6872`
- Wine modification: `patches/0001-mmdevapi-return-ContainerId-as-VT_CLSID.patch`.
- LGPL text: `LICENSE-Wine-LGPL-2.1.txt` alongside this document.

The Wine source archive, our patch and build scripts form the corresponding source
for the Wine-derived binary. Sony's SDK DLL is loaded from the user's installation
and is never packaged. Our helper source and MIT license are in this repository.

## Rebuild Wine DLL

On the tested Apple Silicon Mac, install Xcode command-line tools and Homebrew
`mingw-w64`, `bison`, and `flex`. The recorded compiler was MinGW-w64 14.0.0_3
with GCC 16.2.0; bison 3.8.2 and flex 2.6.4_2.

Extract the release source archive into an empty working directory, then:

```sh
export PATH="/opt/homebrew/opt/bison/bin:/opt/homebrew/opt/flex/bin:$PATH"
cd sources/wine
patch -p1 < /path/to/repository/patches/0001-mmdevapi-return-ContainerId-as-VT_CLSID.patch
mkdir -p ../../build
cd ../../build
../sources/wine/configure --enable-win64 --enable-archs=x86_64 \
  --with-mingw --without-x --without-freetype --disable-tests
make -j8 dlls/mmdevapi/x86_64-windows/mmdevapi.dll
sh /path/to/repository/scripts/link-native-mmdevapi.sh
```

The final relink removes `--wine-builtin`. Without it, the PE file carries the
Wine built-in marker and cannot serve as our native override. This is a packaging
requirement, not an additional audio patch. Do not modify CrossOver.app.

The release DLL hash is
`abb0a074db3a7025c6373eca399748a888ec209cb020c11b807defaaf9e20e22`.
Build timestamps/toolchains can make a rebuilt binary differ; byte-for-byte
reproducibility is not claimed. The release packager intentionally accepts only
the gameplay-validated hash. To release a new build, validate it and update both
the stock/patched hashes and the packager's expected hash.

## Rebuild helper and standalone script

From the repository root:

```sh
mkdir -p dist
x86_64-w64-mingw32-gcc -O2 -Wall -Wextra -municode \
  -o dist/controller-probe.exe src/controller-probe.c \
  -lole32 -luuid -lhid -lsetupapi
python3 scripts/package-release.py \
  --dll /path/to/validated/mmdevapi.dll --probe dist/controller-probe.exe
python3 -m unittest discover -s tests -v
python3 dist/ds2-fix-haptics.py --bottle /path/to/test-bottle --check
```

`dist/ds2-fix-haptics.py` embeds the two binaries and license texts as compressed,
SHA-256-checked assets. The source version of the launcher uses `dist/assets`.
The standalone script itself makes no network requests.

Before publishing, verify permanent install, a new-session check, uninstall,
and reinstall on a test bottle. Verify a normally named Windows helper uses
builtin mmdevapi and a helper named DS2.exe uses the native patched DLL with the
per-executable override. Gameplay validation remains necessary for any changed
Wine/runtime build; passing the property probe alone is not a haptics test.

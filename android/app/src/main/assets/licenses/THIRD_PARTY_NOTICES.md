# Third-Party Notices

FocalCove (专注小窝) is licensed under the Apache License, Version 2.0. It
depends on the third-party components listed below. Each component remains
under its own license; the upstream license text governs. This file is
informational and does not replace those licenses.

Versions reflect the pinned versions in `requirements.txt`,
`requirements-dev.txt`, and `android/app/build.gradle.kts`. Transitive
dependencies may add further notices; run the commands at the end of this
file to inspect the exact resolved set before distributing a binary.

## Web / Python

| Component | Version | License | Project |
| --- | --- | --- | --- |
| Flask | 3.1.2 | BSD-3-Clause | https://flask.palletsprojects.com/ |
| NumPy | 2.4.2 | BSD-3-Clause | https://numpy.org/ |
| opencv-python | 4.13.0.92 | Apache-2.0 (OpenCV) | https://github.com/opencv/opencv-python |
| python-dotenv | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| Gunicorn | 26.2.0 | MIT | https://gunicorn.org/ |
| pytest (development) | 9.0.3 | MIT | https://pytest.org/ |
| ECharts | 5.4.3 | Apache-2.0 | https://echarts.apache.org/ |

### OpenCV and bundled binaries

The `opencv-python` wheel is built by the OpenCV project and may bundle
FFmpeg and other third-party binaries. Those binaries carry their own
licenses (for example LGPL-2.1-or-later for some FFmpeg builds, and
additional component licenses). See the upstream OpenCV and
`opencv-python` distribution for the exact build configuration and
notices. If you redistribute a container image or binary bundle that
includes OpenCV, verify the licenses of its bundled libraries.

### Container base image

The example `Dockerfile` uses an official `python:3.13-slim-bookworm`
image. It contains Debian packages and the Python runtime under their own
licenses; refer to the image's `/usr/share/doc` and the Debian copyright
files for details.

## Android

| Component | Version | License |
| --- | --- | --- |
| AndroidX Core, Activity, Lifecycle | 1.16.0 / 1.10.1 / 2.9.1 | Apache-2.0 |
| Jetpack Compose (BOM, Material 3, UI, tooling) | 2025.06.00 | Apache-2.0 |
| AndroidX Navigation Compose | 2.9.1 | Apache-2.0 |
| AndroidX DataStore | 1.1.7 | Apache-2.0 |
| AndroidX WorkManager | 2.10.2 | Apache-2.0 |
| Kotlin standard library and Compose compiler plugin | 2.x | Apache-2.0 |
| kotlinx-coroutines | 1.10.2 | Apache-2.0 |
| Retrofit | 2.11.0 | Apache-2.0 |
| Gson | via converter-gson 2.11.0 | Apache-2.0 |
| OkHttp | 4.12.0 | Apache-2.0 |
| JUnit | 4.13.2 | EPL-1.0 |
| Hamcrest Core (JUnit dependency) | 1.3 | BSD-3-Clause |
| Gradle Wrapper | 8.11.1 | Apache-2.0 |

AndroidX and Jetpack components are distributed by the Android Open Source
Project under the Apache License, Version 2.0. Kotlin and kotlinx libraries
are distributed by JetBrains under the Apache License, Version 2.0. Retrofit,
Gson, and OkHttp are distributed by Square under the Apache License, Version
2.0. JUnit 4 is distributed under the Eclipse Public License 1.0; Hamcrest
Core is distributed under the BSD 3-Clause license.

## Fonts, icons, and images

The application uses system fonts and does not bundle a third-party webfont.
Material icon vectors come from AndroidX Material Icons (Apache-2.0).
Team-owned scene images, the brand mark, launcher icons, and den furniture
vectors are covered by the project `NOTICE` and are licensed under
Apache-2.0.

## Inspecting the resolved dependency set

Python:

```bash
pip install -r requirements-dev.txt
pip-licenses --format=markdown --with-urls
```

Android:

```bash
cd android
./gradlew :app:dependencies --configuration debugRuntimeClasspath
./gradlew :app:dependencies --configuration testDebugRuntimeClasspath
```

If you add a dependency, update this file in the same change.

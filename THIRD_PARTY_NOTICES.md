# Third-Party Notices

This repository does not redistribute the Huawei CANN installer. The bootstrap
script downloads it from Huawei after explicit license acceptance and verifies
the exact checksum recorded in `dependencies.lock`.

Huawei CANN binaries are governed by the CANN Software User License Agreement
2.0. Review the current agreement before downloading, installing, using, or
redistributing an image containing CANN:

https://www.hiascend.com/legal/cannua-download?isNewCon=true

The implementation was validated against public Huawei examples in
`cann/asc-devkit` and documentation repositories at the commits recorded in
`dependencies.lock`. Those repositories use their respective included license
agreements. Their source is not vendored into this repository.

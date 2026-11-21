# Third-party notices

The project itself is under AGPL-3.0-or-later (`LICENSE`, `NOTICE`). This page lists what it distributes that others
wrote.

The Desktop bundle (`desktop/plugin.js`) contains the packages below, unmodified, as text that the Chat pane writes into
its terminal frame. Nothing else from a third party is distributed in this repository: React and the Hermes plugin SDK
are provided by the Desktop itself, and the Python dependencies are installed from the package index
(`requirements.lock`), not copied here. What is only installed, and under which licence, is listed in
[docs/contributing/dependencies.md](docs/contributing/dependencies.md).

The MIT licence permits distributing this code as part of a work under AGPL-3.0-or-later, provided its copyright and
permission notices are kept: they are kept below and in `LICENSES/MIT.txt`, and `REUSE.toml` marks the bundle as
`AGPL-3.0-or-later AND MIT`.

| Package | Version | Licence | Copyright |
|---|---|---|---|
| `@xterm/xterm` | 5.5.0 | MIT | Copyright (c) 2017-2019, The xterm.js authors (https://github.com/xtermjs/xterm.js); Copyright (c) 2014-2016, SourceLair Private Company (https://www.sourcelair.com); Copyright (c) 2012-2013, Christopher Jeffrey (https://github.com/chjj/) |
| `@xterm/addon-fit` | 0.10.0 | MIT | Copyright (c) 2019, The xterm.js authors (https://github.com/xtermjs/xterm.js) |

## The MIT licence, under which both are used

The same text is in `LICENSES/MIT.txt`.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

# source this: puts the project's pinned tools (SDCC 4.5.0, ucsim-sh68f90, sinowisp) first on PATH
export PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bin:$PATH"

#!/usr/bin/env python
import sys
from glob import glob

from bgexplorer import create_app, main

app = create_app(sys.argv[1] if len(sys.argv)>1 else None)

if __name__ == '__main__':
    main()

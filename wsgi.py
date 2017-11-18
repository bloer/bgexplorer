#!/usr/bin/env python
import sys
from glob import glob

from bgexplorer import create_app

app = create_app(sys.argv[1] if len(sys.argv)>1 else None)

if __name__ == '__main__':
    app.config.update({'DEBUG':True,'TESTING':True, 
                       'TEMPLATES_AUTO_RELOAD':True,
                       #'EXPLAIN_TEMPLATE_LOADING':True,
                      })
    app.secret_key = "not very secret is it?"
    #force template reloading, even though it shouldn't be necessary
    templates = glob("bgexplorer/templates/*.html")
    templates.extend(glob("bgexplorer/*/templates/*.html"))
    app.run(host='0.0.0.0', port=5001, extra_files=templates)           

""" functions and classes for building the bill of materials """
from flask import g
from collections import namedtuple, OrderedDict


BOMRow = namedtuple('BOMRow',('outline','path','component',
                              'weight','totalweight'))

def getbomrows(row=None, form="%02d"):
    """Recursive function to generate list of bomrows
    """
    if not row:
        row = BOMRow(outline='',
                     path=(g.model.assemblyroot,),
                     component=g.model.assemblyroot,
                     weight=1,
                     totalweight=1)
    
    myrows = [row] 

    parent = row.component
    if hasattr(parent,'getcomponents'):
        form = "%02d" if len(parent.components)>10 else "%d"
        for index, cw in enumerate(parent.getcomponents(deep=False, 
                                                        withweight=True)):
            child, weight = cw
            outlineprefix = row.outline+'.' if row.outline else ''
            childrow = BOMRow(outline=("%s"+form)%(outlineprefix,index+1),
                              path=row.path+(child,),
                              component=child,
                              weight=weight,
                              totalweight=row.totalweight*weight)
            myrows.extend(getbomrows(childrow, form=form))
    return myrows
                              

def getdefaultcols():
    """Return an OrderedDict listing columns to show in the bill of materials
    table. Keys are the column headings, and values are functions
    that take a BOMRow as argument. 

    Users extending the bill of materials table should most often extend 
    this list rather than replacing it. If styling is required, 
    results should be wrapped in a <span> element. 
    """
    
    def makelink(url, text, emptylinktext='link'):
        """Embed 'text' in a hyperlink if url is not empty, else return 
        plain text.  If url is not empty but text is, use empylinktext instead
        """
        if url:
            return '<a href="{}">{}</a>'.format(url, 
                                                text if text else emptylinktext)
        else:
            return text
            
    def partnum(row):
        datasheet = row.component.moreinfo.get('datasheet',None)
        partnum = row.component.moreinfo.get('partnum','')
        return makelink(datasheet, partnum, 'datasheet')
            
    def assayref(row):
        return ' '.join(
            makelink(spec.moreinfo.get('url'),
                     spec.moreinfo.get('reference',''), 
                     'ref')
            for spec in row.component.getspecs())
        
    def assaydetail(row):
        return ' '.join(spec.moreinfo.get('refdetail','') + " " + spec.comment
                        for spec in row.component.getspecs())
            
    return OrderedDict((
        ('Weight', lambda r: r.weight),
        ('Description', lambda r: r.component.description),
        ('Comment', lambda r: r.component.moreinfo.get('comment','')),
        ('Partnum', partnum),
        ('Vendor', lambda r: r.component.moreinfo.get('vendor','')),
        ('Assay Ref', assayref),
        ('Assay Detail', assaydetail),
        
        
    ))
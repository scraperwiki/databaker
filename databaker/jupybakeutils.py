# encoding: utf-8
# HTML preview of the dimensions and table (will be moved to a function in databakersolo)
from __future__ import unicode_literals, division

import io
import six
import types

from IPython.display import display
from IPython.core.display import HTML
import databaker.constants
OBS = databaker.constants.OBS   # evaluates to -9

import xypath
from databaker.utils import TechnicalCSV, yield_dimension_values, DUPgenerate_header_row, datematch, template

# This is the main class that does all the work for each dimension
class HDim:
    def __init__(self, hbagset, label, strict=None, direction=None, cellvalueoverride={}):
        self.label = label
        if isinstance(label, int) and label < 0:   # handle human names of the elements for the ONS lookups
            self.name = databaker.constants.template.dimension_names[len(databaker.constants.template.dimension_names)-1+label]
        else:
            self.name = label
            
        assert (type(hbagset) != str), "Use empty set and default value for single value dimension"
        self.hbagset = hbagset
        self.strict = strict
        self.direction = direction
        self.cellvalueoverride = cellvalueoverride
        
        if self.hbagset is None:
            assert self.direction is None and self.strict is None
            return
        assert direction is not None and strict is not None

        self.bxtype = (self.direction[1] == 0)
        self.bbothdirtype = type(self.direction[0]) == tuple or type(self.direction[1]) == tuple
        if self.strict:
            self.samerowlookup = {}
            for hcell in self.hbagset.unordered_cells:
                k = hcell.y if self.bxtype else hcell.x
                if k not in self.samerowlookup:
                    self.samerowlookup[k] = []
                self.samerowlookup[k].append(hcell)
        
            
    def celllookup(self, scell):
        def mult(cell):
            return cell.x * self.direction[0] + cell.y * self.direction[1]
        def dgap(cell, target_cell):
            if direction[1] == 0:
                return abs(cell.x - target_cell.x)
            return abs(cell.y - target_cell.y)
        
        def betweencells(scell, target_cell, best_cell):
            if not self.bbothdirtype:
                if mult(scell) <= mult(target_cell):
                    if not best_cell or mult(target_cell) <= mult(best_cell):
                        return True
                return False
            if not best_cell:
                return True
            return dgap(scell, target_cell) <= dgap(scell, best_cell)
        
        def same_row_col(a, b):
            return  (a.x - b.x  == 0 and self.direction[0] == 0) or (a.y - b.y  == 0 and self.direction[1] == 0)
    
        if self.strict:
            hcells = self.samerowlookup.get(scell.y if self.bxtype else scell.x, [])
        else:
            hcells = self.hbagset.unordered_cells
        hcells = self.hbagset.unordered_cells
        
        best_cell = None
        second_best_cell = None

        #if strict:  print(len(list(hcells)), len(list(hbagset.unordered_cells)))
        for target_cell in hcells:
            if betweencells(scell, target_cell, best_cell):
                if not self.strict or same_row_col(scell, target_cell):
                    second_best_cell = best_cell
                    best_cell = target_cell
        if second_best_cell and not self.bbothdirtype and mult(best_cell) == mult(second_best_cell):
            raise xypath.LookupConfusionError("{!r} is as good as {!r} for {!r}".format(best_cell, second_best_cell, scell))
        if second_best_cell and self.bbothdirtype and dgap(scell, best_cell) == dgap(scell, second_best_cell):
            raise xypath.LookupConfusionError("{!r} is as good as {!r} for {!r}".format(best_cell, second_best_cell, scell))
        if best_cell is None:
            return None
        return best_cell

    def batchcelllookup(self, segment):     
        return [ self.celllookup(ob)  for ob in segment ]

    def procbatch(self, obslist):
        if self.hbagset is None:
            return [ self.singlevalue ]*len(obslist)  # single value type
        dimvalue = self.batchcelllookup(obslist)
        return self.procvalue(dimvalue)

    def Ghdimcellvaluefunc(self, cell):
        if cell is None:
            return "blank"
        if cell in self.cellvalueoverride:
            return self.cellvalueoverride[cell]
        return cell.value


    def procvalue(self, dimvalue):  # redundant
        # Ghdimcellvaluefunc is not really a member function
        return [ self.Ghdimcellvaluefunc(c)  for c in dimvalue ]


    # do the lookup and the value derivation of the cell, via cellvalueoverride{} redirections
    def cellvalobs(self, ob):
        if type(ob) is xypath.xypath.Bag:
            assert len(ob) == 1, "Can only lookupobs a single cell"
            ob = ob._cell
        assert type(ob) is xypath.xypath._XYCell, "Lookups only allowed on an obs cell"
        
        # we do two steps through cellvalueoverride in three places on mutually distinct sets (obs, heading, strings)
        # and not recursively as these are wholly different applications.  the celllookup is itself like a cellvalueoverride
        if ob in self.cellvalueoverride:
            val = self.cellvalueoverride[ob]  # knock out an individual obs for this cell
            assert type(val) is str, "Override from obs should go directly to a string-value"
            return None, val
            
        if self.hbagset is not None:
            hcell = self.celllookup(ob)
        else:
            hcell = None
            
        if hcell is not None:
            assert type(hcell) is xypath.xypath._XYCell, "celllookups should only go to an _XYCell"
            if hcell in self.cellvalueoverride:
                val = self.cellvalueoverride[hcell]
                assert type(val) in (str, float, int), "Override from hcell value should go directly to a str,float,int,None-value (%s)" % type(val)
                return hcell, val
            val = hcell.value
            assert val is None or type(val) in (str, float, int), "cell value should only be str,float,int,None (%s)" % type(val)
        else:
            val = None
        
        # It's allowed to have {None:defaultvalue} to set the NoLookupValue
        if val in self.cellvalueoverride:
            val = self.cellvalueoverride[val]
            assert val is None or type(val) in (str, float, int), "Override from value should only be str,float,int,None (%s)" % type(val)
            
        return hcell, val


from collections import namedtuple
class ConversionSegment(namedtuple('ConversionSegment', ['tab', 'dimensions', 'segment'])):
    def __new__(self, tab, dimensions, segment):
        return super(ConversionSegment, self).__new__(self, tab, dimensions, segment)
        
    def lookupobs(self, ob):
        if type(ob) is xypath.xypath.Bag:
            assert len(ob) == 1, "Can only lookupobs a single cell"
            ob = ob._cell
        dval = { OBS:ob.value }
        for hdim in self.dimensions:
            hcell, val = hdim.cellvalobs(ob)
            dval[hdim.label] = val
        if template.SH_Create_ONS_time:
            if not dval.get(template.TIMEUNIT) and dval.get(template.TIME):
                dval[template.TIMEUNIT] = datematch(dval[template.TIME])
        return dval
        
    def lookupall(self):
        obslist = list(segment.unordered_cells)  # list(segment) otherwise gives bags of one element
        obslist.sort(key=lambda cell: (cell.y, cell.x))
        return [ lookupobs(ob)  for ob in obslist ]



# copied out again
def create_colourlist():
    # Function to dynamically assign colours to dimensions for preview
    "https://github.com/python-excel/xlwt/blob/master/xlwt/Style.py#L309"
    colours = ["lavender", "violet", "gray25", "sea_green",
              "pale_blue", "blue", "gray25", "rose", "tan", "aqua", "light_green", "light_turquoise",
              "light_blue", "sky_blue", "plum", "gold", "lime", "coral", "periwinkle", "ice_blue", "light_yellow"]
    numbers = []
    for i in range(len(databaker.constants.template.dimension_names)-1, \
                   -(len(colours) - len(databaker.constants.template.dimension_names)), -1):
        numbers.append(-i)
    colourlist = dict(list(zip(numbers, colours)))
    return colourlist
colourlist = create_colourlist()
colchange = {"rose":"misty_rose", "ice_blue":"cornflower_blue", "periwinkle":"burly_wood", "pale_blue":"deep_sky_blue", "gray25":"light_gray", "light_turquoise":"pale_turquoise"}


def tsubsets(headers, segment):
    tsubs = [ ]
    if segment:
        tsubs.append((OBS, "OBS", segment))
    for i, header in headers.items():
        if header.direction is not None:   # filter out TempValue headers
            label = header.Dlabel
            if isinstance(label, int) and label < 0:
                label = databaker.constants.template.dimension_names[len(databaker.constants.template.dimension_names)-1+label]
            tsubs.append((i, label, header.bag))
    return tsubs

def dsubsets(dimensions, segment):
    tsubs = [ ]
    if segment:
        tsubs.append((OBS, "OBS", segment))
    for i, dimension in enumerate(dimensions):
        assert type(dimension) != tuple, ("Upgrade to Hdim()", dimension[1])
        if dimension.hbagset is not None:   # filter out TempValue headers
            tsubs.append((i, dimension.name, dimension.hbagset))
    return tsubs


ndividNUM = 1000
dividNUM = "kkkk"
def incrementdividNUM():
    global ndividNUM, dividNUM
    ndividNUM += 1
    dividNUM = "injblock%d" % ndividNUM

def tabletohtml(tab, tsubs):
    key = [ ]
    key.append('Table: <b>%s</b> ' % tab.name)
    key.append('<table class="exkey">\n')
    key.append('<tr>')
    ixyheaderlookup = { }
    for i, label, bag in tsubs:
        for h in bag:
            ixyheaderlookup[(h.x, h.y)] = i
        key.append('<td class="exc%d">%s</td>' % (i, label))
    key.append('</tr>')
    key.append('</table>\n')
    
    sty = [ ]
    sty.append("<style>\n")
    sty.append("table.ex, table.exkey { border: thin black solid }\n")
    sty.append("table.ex td, table.ex tr { border: none }\n")
    sty.append("td.exbold { font-weight: bold }\n")
    sty.append("td.exnumber { color: green }\n")
    sty.append("td.exdate { color: purple }\n")
    sty.append("table { border-collapse: collapse }\n")
    for i, col in colourlist.items():
        sty.append("td.exc%d { background-color: %s }\n" % (i, "".join(lv.capitalize() for lv in colchange.get(col, col).split("_"))))
    sty.append("table.ex td:hover { border: thin blue solid }\n")
    sty.append("table.ex td.exc%d:hover { border: thin red solid }\n" % OBS)
    sty.append("table.ex td.selected { background-color: red; border: thin blue dotted }\n")
    sty.append("</style>\n\n")

    htm = [ ]
    htm.append('<table class="ex">\n')
    for row in tab.rows():
        htm.append("<tr>")
        assert len(row) == tab._max_x + 1
        rrow = sorted(row, key=lambda X: X.x)
        for c in rrow:
            cs = [ ]
            ih = ixyheaderlookup.get((c.x, c.y))
            if ih is not None:             cs.append("exc%d" % ih)
            if c.properties.get_bold():    cs.append("exbold")
            if c.is_date():                cs.append("exdate")
            if c.is_number():              cs.append("exnumber")
            htm.append('<td class="%s" title="%d %d">' % (" ".join(cs), c.x, c.y))
            htm.append(six.text_type(c.value))
            htm.append("</td>")
        htm.append("</tr>\n")
    htm.append("</table>\n")

    jsty = "".join(sty)
    jkey = "".join(key)
    jhtm = "".join(htm)
    return "%s\n%s\n%s\n" % (jsty, jkey, jhtm)

jscode = """
<script>
var jslookup = %s; 
var jdividNUM = "%s"; 
var Dclickedcell = null; 
function clickedcell() 
{ 
    Dclickedcell = this; 
    console.log("jjjj", this); 
    var rgc = new RegExp('(^|\\b)' + "selected".split(' ').join('|') + '(\\b|$)', 'gi'); 
    Array.prototype.forEach.call(document.querySelectorAll("div#"+jdividNUM+" table.ex td.selected"), function(el, i) { 
        if (el.classList)  el.classList.remove("selected");
        else  el.className = el.className.replace(rgc, ' ');
    }); 
    if (this.classList)  this.classList.add("selected");
    else this.className += ' ' + "selected";

    var dimpairs = jslookup[this.title]; 
    if (dimpairs !== undefined) {
        for (var i = 1; i < dimpairs.length; i += 2) {
            var row = document.querySelectorAll("div#"+jdividNUM+" table.ex tr")[dimpairs[i]]; 
            var el = row.querySelectorAll("td")[dimpairs[i-1]]; 
            if (el.classList)  el.classList.add("selected");
            else el.className += ' ' + "selected";
        }
    }
}
Array.prototype.forEach.call(document.querySelectorAll("div#"+jdividNUM+" table.ex td"), function(item, i) { item.onclick=clickedcell; }); 
</script>
"""

# generate the lookup table from titles to references
def calcjslookup(conversionsegment):
    tab, dimensions, segment = conversionsegment
    obslist = list(segment.unordered_cells)  # list(segment) otherwise gives bags of one element

    # should only apply to xypath.xypath.Bag types (alternative is str, which means it's a constant dimension
    dimvalues = [ dimension.batchcelllookup(obslist)  for dimension in dimensions  if dimension.hbagset is not None ]
    jslookup = '{%s}' % ",".join('"%d %d":[%s]' % (k.x, k.y, ",".join("%d,%d" % (d.x, d.y)  for d in tup  if d))  \
                           for k, tup in zip(obslist, zip(*dimvalues)))
    return jslookup
    
    
# could do this as a html-frame and reload
def sidewindowhtmldisplay():
    sjs = '''
<script type="text/Javascript">
var injblock = document.getElementById("%s"); 
console.log(injblock.innerHTML); 
var sidewin = window.open("", "abc123", "toolbar=no,location=no,directories=no,status=no,menubar=no,scrollbars=yes,resizable=yes,width=780,height=200,top=200,left=200"); 
if (sidewin) 
    sidewin.document.body.innerHTML = injblock.innerHTML;
else
    alert("sidewindow didn't work"); 
</script>
'''
    display(HTML(sjs % dividNUM))
    
    
def savepreviewhtml(conversionsegment, fname=None):
    tab, dimensions, segment = conversionsegment

    incrementdividNUM()
    if fname is None:
        fout = io.StringIO()
    else:
        fout = io.open(fname, "w", encoding='utf-8')
        fout.write("<html>\n<head><title>%s</title></head>\n<body>\n" % tab.name)
        
    htmtable = tabletohtml(tab, dsubsets(dimensions, segment))
    fout.write('<div id="%s">\n' % dividNUM)
    fout.write(htmtable)
    fout.write('</div>\n')

    if fname is not None:
        print("tablepart '%s' written" % tab.name)
    if conversionsegment[1] and conversionsegment[2]:
        jslookup = calcjslookup(conversionsegment)
        if fname is not None:
            print("javascript calculated")
        fout.write(jscode % (jslookup, dividNUM))
    
    if fname is None:
        display(HTML(fout.getvalue()))
    else:
        fout.write("</body></html>\n")
        fout.close()
        print("Written to file '%s'" % fname)
    
    
def savepreviewhtmlBAGS(param1, fname=None):
    if type(param1) not in [tuple, list]:
        param1 = [param1]
    tab = None
    dimensions = [ ]
    for i, p in enumerate(param1):
        if not tab:
            tab = p.table
        else:
            assert tab is p.table, "must all be same table"
        if "Table" not in str(type(p)):
            dimensions.append(HDim(p, "item %d"%i, databaker.constants.DIRECTLY, databaker.constants.ABOVE))   # (fake lookup)
    savepreviewhtml((tab, dimensions, []), fname)    


# make a shorter version of the bloated csv    
def procrows(conversionsegment):
    rows = [ ]
    tab, dimensions, segment = conversionsegment
    obslist = list(segment.unordered_cells)  # list(segment) otherwise gives bags of one element
    obslist.sort(key=lambda cell: (cell.y, cell.x))
    dimvalues = [ dimension.procbatch(obslist)  for dimension in dimensions ]
    obsvalues = [ ob.value  for ob in obslist ]
    dtuples = zip(*([ obsvalues ]+dimvalues))
    keys = [OBS] + [ dimension.label  for dimension in dimensions ]  # the labels
    for dtup in dtuples:
        dval = dict(zip(keys, dtup))
        
        # insert the timeunit system
        if template.SH_Create_ONS_time:
            if not dval.get(template.TIMEUNIT) == '' and dval.get(template.TIME):
                # we've not actually been given a timeunit, but we have a time
                # determine the timeunit from the time
                dval[template.TIMEUNIT] = datematch(dval[template.TIME])
        rows.append(dval)

    return rows
    
    
# In theory we can now call the template export to big CSV, like before at this point
# But now we should seek to plot the stats ourselves as a sanity check that the data is good
def writetechnicalCSV(outputfile, conversionsegments):
    csvout = TechnicalCSV(outputfile, False)
    print("writing %d conversion segments into %s" % (len(conversionsegments), outputfile))
    for i, conversionsegment in enumerate(conversionsegments):
        headernames = [None]+[dimension.label  for dimension in conversionsegment[1]  if type(dimension.label) != int ]
        if i == 0:   # only first segment
            header_row = DUPgenerate_header_row(headernames)
            csvout.csv_writer.writerow(header_row)
        rows = procrows(conversionsegment)
        print("conversionwrite segment size %d" % len(rows))
        for row in rows:
            values = dict((k if type(k)==int else headernames.index(k), v)  for k, v in row.items())
            output_row = yield_dimension_values(values, headernames)
            csvout.output(output_row)
    csvout.footer()
    


        

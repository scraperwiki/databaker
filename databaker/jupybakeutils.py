# encoding: utf-8
# HTML preview of the dimensions and table (will be moved to a function in databakersolo)
from __future__ import unicode_literals, division

import six
import io, os, collections, re, warnings
import databaker.constants
OBS = databaker.constants.OBS   # evaluates to -9

import xypath
from databaker.utils import TechnicalCSV, yield_dimension_values, DUPgenerate_header_row, datematch, template

# This is the main class that does all the work for each dimension
class HDim:
    def __init__(self, hbagset, label, strict=None, direction=None, cellvalueoverride=None):
        self.label = label
        if isinstance(label, int) and label < 0:   # handle human names of the elements for the ONS lookups
            self.name = databaker.constants.template.dimension_names[len(databaker.constants.template.dimension_names)-1+label]
        else:
            self.name = label
            
        self.cellvalueoverride = cellvalueoverride or {} # do not put {} into default value otherwise there is only one static one for everything
        assert not isinstance(hbagset, str), "Use empty set and default value for single value dimension"
        self.hbagset = hbagset
        if self.hbagset is None:   # single value type
            assert direction is None and strict is None
            assert len(cellvalueoverride) == 1 and None in cellvalueoverride, "single value type should have cellvalueoverride={None:defaultvalue}"
            return
        
        assert isinstance(self.hbagset, xypath.xypath.Bag), "dimension should be made from xypath.Bag type, not %s" % type(self.hbagset)
        self.strict = strict
        self.direction = direction
        assert direction is not None and strict is not None

        self.bxtype = (self.direction[1] == 0)
        self.bbothdirtype = type(self.direction[0]) == tuple or type(self.direction[1]) == tuple   # prob want to kill off the bothdirtype
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


    # do the lookup and the value derivation of the cell, via cellvalueoverride{} redirections
    def cellvalobs(self, ob):
        if isinstance(ob, xypath.xypath.Bag):
            assert len(ob) == 1, "Can only lookupobs a single cell"
            ob = ob._cell
        assert isinstance(ob, xypath.xypath._XYCell), "Lookups only allowed on an obs cell"
        
        # we do two steps through cellvalueoverride in three places on mutually distinct sets (obs, heading, strings)
        # and not recursively as these are wholly different applications.  the celllookup is itself like a cellvalueoverride
        if ob in self.cellvalueoverride:
            val = self.cellvalueoverride[ob]  # knock out an individual obs for this cell
            assert isinstance(val, str), "Override from obs should go directly to a string-value"
            return None, val
            
        if self.hbagset is not None:
            hcell = self.celllookup(ob)
        else:
            hcell = None
            
        if hcell is not None:
            assert isinstance(hcell, xypath.xypath._XYCell), "celllookups should only go to an _XYCell"
            if hcell in self.cellvalueoverride:
                val = self.cellvalueoverride[hcell]
                assert isinstance(val, (str, float, int)), "Override from hcell value should go directly to a str,float,int,None-value (%s)" % type(val)
                return hcell, val
            val = hcell.value
            assert val is None or isinstance(val, (str, float, int)), "cell value should only be str,float,int,None (%s)" % type(val)
        else:
            val = None
         
        # It's allowed to have {None:defaultvalue} to set the NoLookupValue
        if val in self.cellvalueoverride:
            val = self.cellvalueoverride[val]
            assert val is None or isinstance(val, (str, float, int)), "Override from value should only be str,float,int,None (%s)" % type(val)

        # type call if no other things match
        elif type(val) in self.cellvalueoverride:
             val = self.cellvalueoverride[type(val)](val)
            
        return hcell, val

# convenience helper function/constructor (perhaps to move to the framework module)
def HDimConst(name, val):
    return HDim(None, name, cellvalueoverride={None:val})



class ConversionSegment:
    def __init__(self, tab, dimensions, segment):
        self.tab = tab
        self.dimensions = dimensions
        self.segment = segment   # obs list

        for dimension in self.dimensions:
            assert isinstance(dimension, HDim), ("Dimensions must have type HDim()")
            assert dimension.hbagset is None or dimension.hbagset.table is tab, "dimension %s from different tab" % dimension.name

        # generate the ordered obslist here (so it is fixed here and can be reordered before processing)
        if isinstance(self.segment, xypath.xypath.Bag):
            assert self.segment.table is tab, "segments from different tab"
            self.obslist = list(self.segment.unordered_cells)  # list(segment) otherwise gives bags of one element
            self.obslist.sort(key=lambda cell: (cell.y, cell.x))
        else:
            assert isinstance(self.segment, (tuple, list)), "segment needs to be a Bag or a list, not a %s" % type(self.segment)
            self.obslist = self.segment
            
        # holding place for output of processing.  
        # technically no reason we shouldn't process at this point either, on this constructor, 
        # but doing it in stages allows for interventions along the way
        self.processedrows = None  
            

    # used in tabletohtml for the subsets, and where we would find the mappings for over-ride values
    def dsubsets(self):
        tsubs = [ ]
        if self.segment:
            tsubs.append((OBS, "OBS", self.segment))
        for i, dimension in enumerate(self.dimensions):
            if dimension.hbagset is not None:   # filter out TempValue headers
                tsubs.append((i, dimension.name, dimension.hbagset))
        return tsubs
        
    # individual lookup across the dimensions here
    def lookupobs(self, ob):
        if type(ob) is xypath.xypath.Bag:
            assert len(ob) == 1, "Can only lookupobs a single cell"
            ob = ob._cell
        dval = { OBS:ob.value }
        for hdim in self.dimensions:
            hcell, val = hdim.cellvalobs(ob)
            dval[hdim.label] = val
        return dval
        
    def lookupall(self):   # defunct function
        return [ self.lookupobs(ob)  for ob in self.obslist ]

    def process(self):
        assert self.processedrows is None, "Conversion segment already processed"
        self.processedrows = [ self.lookupobs(ob)  for ob in self.obslist ]
        
    def guesstimeunit(self):
        for dval in self.processedrows:
            dval[template.TIMEUNIT] = datematch(dval[template.TIME])
        ctu = collections.Counter(dval[template.TIMEUNIT]  for dval in self.processedrows)
        if len(ctu) == 1:
            return "TIMEUNIT='%s'" % list(ctu.keys())[0]
        return "multiple TIMEUNITs: %s" % ", ".join("'%s'(%d)" % (k,v)  for k,v in ctu.items())
        
    def fixtimefromtimeunit(self):
        for dval in self.processedrows:
            if dval[template.TIMEUNIT] == 'Year':
                st = str(dval[template.TIME]).strip()
                mst = re.match("(\d\d\d\d)(?:\.0)?$", st)
                if mst:
                    dval[template.TIME] = mst.group(1)
                else:
                    warnings.warn("TIME %s disagrees with TIMEUNIT %s" % (st, dval[template.TIMEUNIT]))
            if datematch(dval[template.TIME]) != dval[template.TIMEUNIT]:
                warnings.warn("TIME %s disagrees with TIMEUNIT %s" % (dval[template.TIME], dval[template.TIMEUNIT]))
                

    
# In theory we can now call the template export to big CSV, like before at this point
# But now we should seek to plot the stats ourselves as a sanity check that the data is good
def writetechnicalCSV(outputfile, conversionsegments):
    if type(conversionsegments) is ConversionSegment:
        conversionsegments = [conversionsegments]
    csvout = TechnicalCSV(outputfile, False)
    if outputfile is not None:
        print("writing %d conversion segments into %s" % (len(conversionsegments), os.path.abspath(outputfile)))
        
    for i, conversionsegment in enumerate(conversionsegments):
        headernames = [None]+[dimension.label  for dimension in conversionsegment.dimensions  if type(dimension.label) != int ]
        if i == 0:   # only first segment
            header_row = DUPgenerate_header_row(headernames)
            csvout.csv_writer.writerow(header_row)
            
        if conversionsegment.processedrows is None: 
            conversionsegment.process()  
            
        kdim = dict((dimension.label, dimension)  for dimension in conversionsegment.dimensions)
        timeunitmessage = ""
        if template.SH_Create_ONS_time and ((template.TIMEUNIT not in kdim) and (template.TIME in kdim)):
            timeunitmessage = conversionsegment.guesstimeunit()
            conversionsegment.fixtimefromtimeunit()
        elif template.TIME in kdim and template.TIMEUNIT not in kdim:
            conversionsegment.fixtimefromtimeunit()

        if outputfile is not None:
            print("conversionwrite segment size %d table '%s; %s" % (len(conversionsegment.processedrows), conversionsegment.tab.name, timeunitmessage))
        for row in conversionsegment.processedrows:
            values = dict((k if type(k)==int else headernames.index(k), v)  for k, v in row.items())
            output_row = yield_dimension_values(values, headernames)
            csvout.output(output_row)
    csvout.footer()
    if csvout.filename is None:
        print(csvout.filehandle.getvalue())


        

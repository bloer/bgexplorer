import operator
import numpy as np

class Histogram(object):
    """2-tuple mimicking np.histogram structure, with operator overloads
    so that bins are not added/scaled etc 
    """
    def __init__(self, hist, bin_edges=None):
        self.hist = np.array(hist)
        self.bin_edges = bin_edges
        if bin_edges is None:
            self.bin_edges = np.arange(len(self.hist))
            

    def find_bin(self, x):
        """Find the index of the bin where x is.
        Args: 
            x (float): value to search for. must have same units as bins
        Returns:
            bin (int): will be -1 if before first bin, Nbins if outside last bin
        """
        return self.bin_edges.searchsorted(x, 'right')-1
        
    def val(self, x, interp=None):
        """Get the value of the histogram at x. x must be in the same 
        units as the bins. 
        Args:
            x (float): Value to test
            interp (str): Currently: if truthy, linearly interpolate the value
                          between bins. For future use: accept string
                          specifying interpolation method
        Returns:
            val (float): value of bin where x is, None if x is outside bins
        """
        bin = self.find_bin(x)
        if x<0 or x >= len(self.hist):
            return None
        val = self.hist[bin]
        if interp and bin < len(self.hist)-1:
            slope = ( (self.hist[bin+1]-self.hist[bin]) /
                      (self.bin_edges[bin+1]-self.bin_edges[bin]) )
            val += slope * (x-self.bin_edges[bin])
        return val

    def _bound(self, a, b, bins=None):
        """coerce a and b to the edges of bins"""
        if bins is None:
            bins = self.bin_edges
        if a is None or a < bins[0]:
            a = bins[0]
        if b is None or b >= bins[-1]:
            b = bins[-1]
        return (a, b)
        
    def integrate(self, a=None, b=None, binwidth=True):
        """Integrate the histogram from a to b. If a and b do not correspond to 
        exact bin edges, the value in the bin will be interpolated. 

        Args:
            a (float): low range. If bin_edges has units, this must have the 
                       same dimensionality. IF bin_edges is None, this will
                       be treated as a bin index. if None, use low bound
            b (float): upper edge. if None, use upper bound
            binwidth (bool): if True (default), multiply each bin by the bin
                             width. If False, just add bin values
        """
        bins = self.bin_edges 
        spec = self.hist
        a, b = self._bound(a,b)
        if binwidth:
            spec = spec * (bins[1:]-bins[:-1]) 
        
        first = bins.searchsorted(a,"right")
        last = bins.searchsorted(b,"left")
        #take fractions of the first and last bins
        if first == last:
            return spec[first-1] * (b-a)/(bins[first]-bins[first-1])
        return ( spec[first-1] * (bins[first]-a)/(bins[first]-bins[first-1])
                 +spec[last-1] * (b-bins[last-1])/(bins[last]-bins[last-1])
                 +sum(spec[first:max(last-1,first)])
             )

    def average(self, a=None, b=None, binwidths=True):
        """Calculate the average from a to b. See `integrate` for description
        of the arguments
        """
        a, b = self._bound(a,b)
        return self.integrate(a, b, binwidths) / (b-a)

    
    def _testbins(self, other):
        try:
            otherbins = other.bin_edges
        except AttributeError:
            return self.bin_edges
        if otherbins is None:
            return self.bin_edges
        elif self.bin_edges is None:
            return otherbins
        elif not np.array_equal(self.bin_edges,otherbins):
            msg = ("Can't combins histograms with different binning: %s and %s"
                   %(self.bin_edges, otherbins))
            raise ValueError(msg)
        return self.bin_edges

    def _combine(self, other, op, inplace=False):
        #treat None as zero 
        
        #make sure bins are equal 
        bins = self._testbins(other)

        try:
            otherhist = other.hist
        except AttributeError:
            #how to tell the difference between a 2-tuple and 1D array???
            otherhist = other
        
        if inplace:
            self.hist = op(self.hist, otherhist)
            return self
        else:
            return self.__class__(op(self.hist,otherhist), bins)

        
    #todo: should we provide for adding raw spectra rather than just Histograms?
    #binary copy operators    
    def __add__(self, other):
        if other is None:
            other = 0
        return self._combine(other, operator.add)
     
    def __sub__(self, other):
        if other is None:
            other = 0
        return self._combine(other, operator.sub)
    
    def __mul__(self, other):
        if other is None:
            other = 0
        return self._combine(other, operator.mul)
    
    def __floordiv__(self, other):
        return self._combine(other, operator.floordiv)
    
    def __truediv__(self, other):
        return self._combine(other, operator.truediv)
    
    def __mod__(self, other):
        return self._combine(other, operator.mod)
    
    def __pow__(self, other):
        return self._combine(other, operator.pow)
    
    #do we need logical/bitwise operators??
        
    #binary in-place operators
    def __iadd__(self, other):
        if other is None:
            other = 0
        return self._combine(other, operator.iadd, inplace=True)
     
    def __isub__(self, other):
        if other is None:
            other = 0
        return self._combine(other, operator.isub, inplace=True)
    
    def __imul__(self, other):
        if other is None:
            other = 0
        return self._combine(other, operator.imul, inplace=True)
    
    def __ifloordiv__(self, other):
        return self._combine(other, operator.ifloordiv, inplace=True)
    
    def __itruediv__(self, other):
        return self._combine(other, operator.itruediv, inplace=True)
    
    def __imod__(self, other):
        return self._combine(other, operator.imod, inplace=True)
    
    def __ipow__(self, other):
        return self._combine(other, operator.ipow, inplace=True)

    #reverse binary operators
    #these should only ever be called if type(other) != type(self)
    def __radd__(self, other):
        if other is None:
            other = 0
        return self.__class__(other + self.hist, self.bin_edges)
     
    def __rsub__(self, other):
        if other is None:
            other = 0
        return self.__class__(other - self.hist, self.bin_edges)
    
    def __rmul__(self, other):
        if other is None:
            other = 0
        return self.__class__(other * self.hist, self.bin_edges)
    
    def __rfloordiv__(self, other):
        return self.__class__(other // self.hist, self.bin_edges)
    
    def __rtruediv__(self, other):
        return self.__class__(other / self.hist, self.bin_edges)
    
    def __rmod__(self, other):
        return self.__class__(other % self.hist, self.bin_edges)
    
    def __rpow__(self, other):
        return self.__class__(other ** self.hist, self.bin_edges)
    
    
    
    #unary operators
    def __neg__(self):
        return self.__class__(-self.hist, self.bin_edges)
    
    def __abs__(self):
        return self.__class__(abs(self.hist), self.bin_edges)
        
    
    
    

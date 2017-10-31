import uuid
import copy

class Mappable(object):
    """ Mappable is a basic class to ensure an object has a hashable ID """
    
    def __init__(self, _id=None, **kwargs):
        super().__init__(**kwargs)
        self._id = _id or str(uuid.uuid4())
    
    @property
    def id(self):
        return self._id

    def clone(self, newname=None, deep=True):
        clone = copy.deepcopy(self) if deep else copy.copy(self)
        clone._id = str(uuid.uuid4())
        if newname and hasattr(clone, 'name'):
            clone.name = newname
        return clone
        
    def __eq__(self, other):
        try:
            return self.id == other.id
        except:
            return False #should we test self.id == other?

    def __hash__(self):
        return hash(self.id)

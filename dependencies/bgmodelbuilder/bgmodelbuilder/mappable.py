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


    def clone(self, newname=None):
        clone = copy.deepcopy(self)
        clone._id = str(uuid.uuid4())
        if hasattr(clone, 'name'):
            setattr(clone,'name', newname or "Copy of "+clone.name)
        return clone
        
    def __eq__(self, other):
        try:
            return self.id == other.id
        except:
            return False

    def __hash__(self):
        return hash(self.id)

import uuid

class Mappable(object):
    """ Mappable is a basic class to ensure an object has a hashable ID """
    
    def __init__(self, _id=None, **kwargs):
        super().__init__(**kwargs)
        self._id = _id or str(uuid.uuid4())
    
    @property
    def id(self):
        return self._id



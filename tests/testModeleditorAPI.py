""" This is a standin for a test case against the api.
"""
from .base import BGExplorerTestCase


class TestModelEditorAPI(BGExplorerTestCase):

  def create_model(self):
    """
     Convenience function for using the test client
     to create a model and return the model id.

     The string parsing is a little hacky, but will be replaced
     with a list feature in later development.
     TODO: The above.
    """
    response = self.client.post('/models/new')
    self.check_valid_endpoint(response)
    assert(response.status_code == 302)
    data = response.data.decode('utf-8')
    modelid = data.split('/edit/')[1].split('/')[0]
    return modelid

  def create_component_for_model(self, modelid):
    """
      Convenience function for using the test client
      to create components within a model.

      TODO: replace string parsing.
    """
    response = self.client.post('/models/edit/{}/newcomponent'.format(modelid))
    self.check_valid_endpoint(response)
    assert(response.status_code == 302)
    componentid = response.data.decode('utf-8').split('editcomponent/')[1].split('\"')[0]
    assert(len(componentid) == 36) # valid component ID check... TODO: needs more.
    return componentid

  def create_spec_for_model(self, modelid):
    """
      Convenience function for using the test client
      to create specifications within a model      
    """
    response = self.client.post('/models/edit/{}/newspec'.format(modelid))
    self.check_valid_endpoint(response)
    assert(response.status_code == 302)
    specid = response.data.decode('utf-8').split('editspec/')[1].split('\"')[0]
    return specid

  def test_newmodel(self):
    modelid = self.create_model()
    assert(modelid is not None)

  def test_editmodel(self):
    response = self.client.post('/models/new', follow_redirects=True)
    self.check_valid_endpoint(response)
    assert(response.status_code == 200)

  def test_savemodel(self):
    modelid = self.create_model()
    # TODO: Currently, save models does not work. Once savemodel has been implemented, uncomment these lines
    #response = self.client.post('/models/edit/{}/save'.format(modelid))
    #self.check_valid_endpoint(response)

  def test_getmodelordie(self):
    modelid = self.create_model()
    try:
      response = self.client.post('/models/edit/{}/'.format('0'))
    except:
      assert(True)
    else:
      assert(False)

  def test_newcomponent(self):
    modelid = self.create_model()
    componentid = self.create_component_for_model(modelid)

  def test_delcomponent(self):
    modelid = self.create_model()
    componentid = self.create_component_for_model(modelid)
    response = self.client.post('/models/edit/{}/delcomponent/{}'.format(modelid, componentid))
    self.check_valid_endpoint(response)

  def test_placement(self):
    modelid = self.create_model()
    component1 = self.create_component_for_model(modelid)
    component2 = self.create_component_for_model(modelid)
    # TODO: the below fails. figure out why
    #response = self.client.post('/models/edit/{}/newplacement/{}/{}'.format(modelid,
    #  component1, component2))
    #self.check_valid_endpoint(response)

  def test_newspec(self):
    modelid = self.create_model()
    specid = self.create_spec_for_model(modelid)
    assert(specid is not None)

  def test_delspec(self):
    modelid = self.create_model()
    specid = self.create_spec_for_model(modelid)
    response = self.client.post('/models/edit/{}/delspec/{}'.format(modelid,
                                                                    specid))
    self.check_valid_endpoint(response)

  def test_attachspec(self):
    modelid = self.create_model()
    specid = self.create_spec_for_model(modelid)
    componentid = self.create_component_for_model(modelid)
    response = self.client.post('/models/edit/{}/attachspec/{}/{}'.format(modelid,
                                                                          componentid,
                                                                          specid))
    self.check_valid_endpoint(response)

  def test_detachspec(self):
    modelid = self.create_model()
    specid = self.create_spec_for_model(modelid)
    componentid = self.create_component_for_model(modelid)
    response = self.client.post('/models/edit/{}/attachspec/{}/{}'.format(modelid,
                                                                          componentid,
                                                                          specid))
    self.check_valid_endpoint(response)
    response = self.client.post('/models/edit/{}/detachspec/{}/{}'.format(modelid,
                                                                          componentid,
                                                                          0))
    self.check_valid_endpoint(response)
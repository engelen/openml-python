from collections import OrderedDict

import openml
import xmltodict

from .setup import OpenMLSetup, OpenMLParameter
from openml.flows import flow_exists


def setup_exists(flow, model=None):
    '''
    Checks whether a hyperparameter configuration already exists on the server.

    Parameter
    ---------

    flow : flow
        The openml flow object.

    sklearn_model : BaseEstimator, optional
        If given, the parameters are parsed from this model instead of the
        model in the flow. If not given, parameters are parsed from
        ``flow.model``.

    Returns
    -------
    setup_id : int
        setup id iff exists, False otherwise
    '''

    # sadly, this api call relies on a run object
    openml.flows.functions._check_flow_for_server_id(flow)

    if model is None:
        model = flow.model
    else:
        exists = flow_exists(flow.name, flow.external_version)
        if exists != flow.flow_id:
            raise ValueError('This should not happen!')

    openml_param_settings = openml.runs.OpenMLRun._parse_parameters(flow, model)
    description = xmltodict.unparse(_to_dict(flow.flow_id,
                                             openml_param_settings),
                                    pretty=True)
    file_elements = {'description': ('description.arff', description)}

    result = openml._api_calls._perform_api_call('/setup/exists/',
                                                 file_elements=file_elements)
    result_dict = xmltodict.parse(result)
    setup_id = int(result_dict['oml:setup_exists']['oml:id'])
    if setup_id > 0:
        return setup_id
    else:
        return False


def get_setup(setup_id):
    '''
     Downloads the setup (configuration) description from OpenML
     and returns a structured object

    Parameters
        ----------
        setup_id : int
            The Openml setup_id

        Returns
        -------
        OpenMLSetup
            an initialized openml setup object
    '''
    result = openml._api_calls._perform_api_call('/setup/%d' %setup_id)
    result_dict = xmltodict.parse(result)
    return _create_setup_from_xml(result_dict)


def list_setups(flow=None, tag=None, setup=None, offset=None, size=None):
    """List all setups matching all of the given filters.

        Perform API call `/setup/list/{filters}

        Parameters
        ----------
        flow : int, optional

        tag : str, optional

        setup : list(int), optional

        offset : int, optional

        size : int, optional

        Returns
        -------
        list
            List of found setups.
        """

    api_call = "setup/list"
    if offset is not None:
        api_call += "/offset/%d" % int(offset)
    if size is not None:
        api_call += "/limit/%d" % int(size)
    if setup is not None:
        api_call += "/setup/%s" % ','.join([str(int(i)) for i in setup])
    if flow is not None:
        api_call += "/flow/%s" % flow
    if tag is not None:
        api_call += "/tag/%s" % tag

    return _list_setups(api_call)


def _list_setups(api_call):
    """Helper function to parse API calls which are lists of setups"""

    xml_string = openml._api_calls._perform_api_call(api_call)

    setups_dict = xmltodict.parse(xml_string)
    # Minimalistic check if the XML is useful
    if 'oml:setups' not in setups_dict:
        raise ValueError('Error in return XML, does not contain "oml:setups": %s'
                         % str(setups_dict))
    elif '@xmlns:oml' not in setups_dict['oml:setups']:
        raise ValueError('Error in return XML, does not contain '
                         '"oml:setups"/@xmlns:oml: %s'
                         % str(setups_dict))
    elif setups_dict['oml:setups']['@xmlns:oml'] != 'http://openml.org/openml':
        raise ValueError('Error in return XML, value of  '
                         '"oml:seyups"/@xmlns:oml is not '
                         '"http://openml.org/openml": %s'
                         % str(setups_dict))

    if isinstance(setups_dict['oml:setups']['oml:setup'], list):
        setups_list = setups_dict['oml:setups']['oml:setup']
    elif isinstance(setups_dict['oml:setups']['oml:setup'], dict):
        setups_list = [setups_dict['oml:setups']['oml:setup']]
    else:
        raise TypeError()

    setups = dict()
    for setup_ in setups_list:
        # making it a dict to give it the right format
        current = _create_setup_from_xml({'oml:setup_parameters': setup_})
        setups[current.setup_id] = current

    return setups


def initialize_model(setup_id):
    '''
    Initialized a model based on a setup_id (i.e., using the exact
    same parameter settings)

    Parameters
        ----------
        setup_id : int
            The Openml setup_id

        Returns
        -------
        model : sklearn model
            the scikitlearn model with all parameters initailized
    '''

    # transform an openml setup object into
    # a dict of dicts, structured: flow_id maps to dict of
    # parameter_names mapping to parameter_value

    setup = get_setup(setup_id)
    parameters = {}
    for _param in setup.parameters:
        _flow_id = setup.parameters[_param].flow_id
        _param_name = setup.parameters[_param].parameter_name
        _param_value = setup.parameters[_param].value
        if _flow_id not in parameters:
            parameters[_flow_id] = {}
        parameters[_flow_id][_param_name] = _param_value

    def _reconstruct_flow(_flow, _params):
        # recursively set the values of flow parameters (and subflows) to
        # the specific values from a setup. _params is a dict of
        # dicts, mapping from flow id to param name to param value
        # (obtained by using the subfunction _to_dict_of_dicts)
        for _param in _flow.parameters:
            # It can happen that no parameters of a flow are in a setup,
            # then the flow_id is not in _params; usually happens for a
            # sklearn.pipeline.Pipeline object, where the steps parameter is
            # not in the setup
            if _flow.flow_id not in _params:
                continue
            # It is not guaranteed that a setup on OpenML has all parameter
            # settings of a flow, thus a param must not be in _params!
            if _param not in _params[_flow.flow_id]:
                continue
            _flow.parameters[_param] = _params[_flow.flow_id][_param]
        for _identifier in _flow.components:
            _flow.components[_identifier] = _reconstruct_flow(_flow.components[_identifier], _params)
        return _flow

    # now we 'abuse' the parameter object by passing in the
    # parameters obtained from the setup
    flow = openml.flows.get_flow(setup.flow_id)
    flow = _reconstruct_flow(flow, parameters)

    return openml.flows.flow_to_sklearn(flow)


def _to_dict(flow_id, openml_parameter_settings):
    # for convenience, this function (ab)uses the run object.
    xml = OrderedDict()
    xml['oml:run'] = OrderedDict()
    xml['oml:run']['@xmlns:oml'] = 'http://openml.org/openml'
    xml['oml:run']['oml:flow_id'] = flow_id
    xml['oml:run']['oml:parameter_setting'] = openml_parameter_settings

    return xml

def _create_setup_from_xml(result_dict):
    '''
     Turns an API xml result into a OpenMLSetup object
    '''
    setup_id = int(result_dict['oml:setup_parameters']['oml:setup_id'])
    flow_id = int(result_dict['oml:setup_parameters']['oml:flow_id'])
    parameters = {}
    if 'oml:parameter' not in result_dict['oml:setup_parameters']:
        parameters = None
    else:
        # basically all others
        xml_parameters = result_dict['oml:setup_parameters']['oml:parameter']
        if isinstance(xml_parameters, dict):
            id = int(xml_parameters['oml:id'])
            parameters[id] = _create_setup_parameter_from_xml(xml_parameters)
        elif isinstance(xml_parameters, list):
            for xml_parameter in xml_parameters:
                id = int(xml_parameter['oml:id'])
                parameters[id] = _create_setup_parameter_from_xml(xml_parameter)
        else:
            raise ValueError('Expected None, list or dict, received someting else: %s' %str(type(xml_parameters)))

    return OpenMLSetup(setup_id, flow_id, parameters)

def _create_setup_parameter_from_xml(result_dict):
    return OpenMLParameter(int(result_dict['oml:id']),
                           int(result_dict['oml:flow_id']),
                           result_dict['oml:full_name'],
                           result_dict['oml:parameter_name'],
                           result_dict['oml:data_type'],
                           result_dict['oml:default_value'],
                           result_dict['oml:value'])

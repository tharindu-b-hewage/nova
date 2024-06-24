# Copyright (c) 2016, Red Hat Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
CPU Weigher.  Weigh hosts by their CPU usage.

The default is to spread instances across all hosts evenly.  If you prefer
stacking, you can set the 'cpu_weight_multiplier' option (by configuration
or aggregate metadata) to a negative number and the weighing has the opposite
effect of the default.
"""
import math

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights
from ..manager import CORE_USAGE

CONF = nova.conf.CONF


class CPUWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'cpu_weight_multiplier',
            CONF.filter_scheduler.cpu_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""
        hints = weight_properties.scheduler_hints
        if not (type in hints):
            vcpus_free = (
                    host_state.vcpus_total * host_state.cpu_allocation_ratio -
                    host_state.vcpus_used)
            return vcpus_free

        # get criticality of the VM.
        is_evct = hints['type'][0] == 'evictable'

        # get green cores metrics.
        host_ip = host_state.host_ip
        core_usage = list(filter(lambda x: x['host-ip'] == str(host_ip), CORE_USAGE['core_usage']))
        core_usage = core_usage[0]

        # map host to the Euclidean space.
        rcpus_avl = core_usage['reg-cores-avl']
        rcpus_used = core_usage['reg-cores-usg']
        gcpus_avl = core_usage['green-cores-avl']
        gcpus_used = core_usage['green-cores-usg']
        p_host = {
            'deficit': abs(rcpus_avl - rcpus_used) / rcpus_avl,
            'promise': abs(gcpus_avl - gcpus_used) / gcpus_avl
        }

        ''' Tuned reference values.
        Values were evaluated from large-scale experiments, tuned to provide a balance between evictions and 
        harvest.
        '''
        ref_vals = {
            'p_ref_reg': {
                'promise': 1.0,
                'deficit': 0.0625
            },
            'p_ref_evct': {
                'promise': 0.2,
                'deficit': 0.0
            }
        }

        # calculate the distance between the host and the reference point.
        p_ref = ref_vals['p_ref_evct'] if is_evct else ref_vals['p_ref_reg']
        distance = math.sqrt(
            math.pow(p_host['deficit'] - p_ref['deficit'], 2)
            + math.pow(p_host['promise'] - p_ref['promise'], 2)
        )
        final_weight = 1 - distance
        return final_weight

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
from oslo_log import log as logging

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class CPUWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'cpu_weight_multiplier',
            CONF.filter_scheduler.cpu_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""

        LOG.info("[OpenStack-GC] cpu_weight_multiplier: %(cpu_weight_multiplier)s", {'cpu_weight_multiplier': utils.get_weight_multiplier(
            host_state, 'cpu_weight_multiplier',
            CONF.filter_scheduler.cpu_weight_multiplier)})

        host_ip = host_state.host_ip
        hints = weight_properties.scheduler_hints
        if not ('type' in hints):
            LOG.info("[OpenStack-GC] 'type' hint is not provided. Engaging nova's default cpu weighter.")
            LOG.info("[OpenStack-GC] available scheduler_hints: %(hints)s", {'hints': hints})
            vcpus_free = (
                    host_state.vcpus_total * host_state.cpu_allocation_ratio -
                    host_state.vcpus_used)
            LOG.info('[OpenStack-GC] node: %(host_ip)s | vcpus_free: %(vcpus_free)d', {'host_ip': host_ip, 'vcpus_free': vcpus_free})
            return vcpus_free

        LOG.info("[OpenStack-GC] 'type' hint is found. Engaging Green Cores packing algorithm.")

        # get criticality of the VM.
        is_evct = hints['type'][0] == 'evictable'

        # get green cores metrics.
        core_usage = list(filter(lambda x: x['host-ip'] == str(host_ip), CORE_USAGE['core_usage']))
        core_usage = core_usage[0]
        LOG.info('[OpenStack-GC] node: %(host_ip)s | core_usage: %(core_usage)s', {'host_ip': host_ip, 'core_usage': core_usage})

        # map host to the Euclidean space.
        rcpus_avl = core_usage['reg-cores-avl']
        rcpus_used = core_usage['reg-cores-usg']
        gcpus_avl = core_usage['green-cores-avl']
        gcpus_used = core_usage['green-cores-usg']
        p_host = {
            'deficit': abs(rcpus_avl - rcpus_used) / rcpus_avl,
            'promise': abs(gcpus_avl - gcpus_used) / gcpus_avl
        }
        LOG.info('[OpenStack-GC] node: %(host_ip)s | node_coordinates: %(p_host)s', {'host_ip': host_ip, 'p_host': p_host})

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
        LOG.info('[OpenStack-GC] node: %(host_ip)s | ref_coordinates: %(p_ref)s', {'host_ip': host_ip, 'p_ref': p_ref})

        distance = math.sqrt(
            math.pow(p_host['deficit'] - p_ref['deficit'], 2)
            + math.pow(p_host['promise'] - p_ref['promise'], 2)
        )
        final_weight =  math.sqrt(2) - distance
        LOG.info('[OpenStack-GC] node: %(host_ip)s | final_weight: %(final_weight)s', {'host_ip': host_ip, 'final_weight': final_weight})

        return final_weight

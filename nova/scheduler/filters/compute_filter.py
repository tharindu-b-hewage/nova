# Copyright (c) 2012 OpenStack Foundation
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

from oslo_log import log as logging

from nova.scheduler import filters
from nova import servicegroup
from ..manager import CORE_USAGE

LOG = logging.getLogger(__name__)


class ComputeFilter(filters.BaseHostFilter):
    """Filter on active Compute nodes."""

    RUN_ON_REBUILD = False

    def __init__(self):
        self.servicegroup_api = servicegroup.API()

    # Host state does not change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, spec_obj):
        """Returns True for only active compute nodes."""
        service = host_state.service
        if service['disabled']:
            LOG.debug("%(host_state)s is disabled, reason: %(reason)s",
                      {'host_state': host_state,
                       'reason': service.get('disabled_reason')})
            return False
        else:
            if not self.servicegroup_api.service_is_up(service):
                LOG.warning("%(host_state)s has not been heard from in a "
                            "while", {'host_state': host_state})
                return False

        host_ip = host_state.host_ip
        core_usage = list(filter(lambda x: x['host-ip'] == str(host_ip), CORE_USAGE['core_usage']))
        core_usage = core_usage[0]

        gcpus_avl = core_usage['green-cores-avl']

        hints = spec_obj.scheduler_hints
        is_low_lat_type = hints['is_low_latency'][0] if 'is_low_latency' in hints else 'false'
        scheduler = hints['scheduler'][0]

        if scheduler == 'load_shift':
            LOG.info("[SMT-POOLING-SCH] Scheduler: %(scheduler)s", {'scheduler': scheduler})
            if str(host_ip) == '172.23.13.35' and is_low_lat_type == 'true':
                LOG.info(
                    "[SMT-POOLING-SCH] Cannot pack low-latency VM in the SMT host when scheduler: %(scheduler)s is used",
                    {'scheduler': scheduler})
                return False
            LOG.info("[SMT-POOLING-SCH] Can pack - scheduler: %(scheduler)s", {'scheduler': scheduler})
            return True

        LOG.info("[SMT-POOLING-SCH] Scheduler: %(scheduler)s", {'scheduler': scheduler})
        if is_low_lat_type == 'true':
            LOG.info("[SMT-POOLING-SCH] type: %(is_low_lat_type)s is low-latency. filtering...",
                     {'is_low_lat_type': is_low_lat_type})
            if str(host_ip) == '172.23.13.34':
                if int(gcpus_avl) == 6:
                    LOG.info(
                        "[SMT-POOLING-SCH] host_ip: %(host_ip)s is in non-SMT pool and is at rnw peak. Can place Low-lat VM here!",
                        {'host_ip': str(host_ip)})
                    return True
                else:
                    LOG.info(
                        "[SMT-POOLING-SCH] host_ip: %(host_ip)s is in non-SMT pool and is at rnw valley. Cannot place Low-lat VM here!",
                        {'host_ip': str(host_ip)})
                    return False
            else:
                LOG.info("[SMT-POOLING-SCH] host_ip: %(host_ip)s is in SMT pool. Cannot place Low-lat VM here...",
                         {'host_ip': str(host_ip)})
                return False
        else:
            if str(host_ip) == '172.23.13.34' and int(gcpus_avl) == 6:
                LOG.info(
                    "[SMT-POOLING-SCH] type: %(is_low_lat_type)s is not low-latency. But current host is non-SMT at rnw peak, so avoiding placing best-effort VMs here!",
                    {'is_low_lat_type': is_low_lat_type})
                return False
            LOG.info("[SMT-POOLING-SCH] type: %(is_low_lat_type)s is not low-latency. Will be unfiltered",
                     {'is_low_lat_type': is_low_lat_type})

        return True

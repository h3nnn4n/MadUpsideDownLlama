import random
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2


class WorkerController:
    def __init__(self, bot=None, verbose=False):
        self.verbose = False  # verbose
        self.bot = bot

        self.auto_build_worker = False
        self.auto_handle_idle_workers = True

        self.priority = ['MINERAL', 'GAS']

        self.number_of_near_scouts = 1
        self.number_of_global_scouts = 0
        self.number_of_scouting_workers = (
            self.number_of_near_scouts +
            self.number_of_global_scouts
        )
        self.number_of_near_expansions_to_scout = 5
        self.scouting_workers = {}
        self.scouting_queue = []

        self.worker_unit_types = [
            UnitTypeId.DRONE,
            UnitTypeId.PROBE,
            UnitTypeId.SCV
        ]
        self.threat_proximity = 40
        self.proxy_proximity = 80
        self.militia = {}
        self.nearby_enemy_workers_found = {}
        self.nearby_enemy_units_found = {}
        self.nearby_enemy_structures_found = {}
        self.number_of_units_to_attack_enemy_workers = 2

        self.max_workers_on_gas = 9
        self.current_workers_on_gas = 0

        self.maximum_workers = 66

        self.mineral_field_cache = {}
        self.idle_workers = {}

        self.nexus = {}

        self.on_nexus_ready_do = [self.redistribute_workers]
        self.on_mineral_field_depleted_do = [self.redistribute_workers]

        self.mineral_field_count = 0
        self.mineral_field_count_timer = 0
        self.mineral_field_count_cooldown = 10

    async def step(self):
        self.update_threats()
        await self.step_scouting_workers()
        await self.step_militia_workers()
        self.update_worker_count_on_gas()
        await self.build_workers()
        await self.handle_idle_workers()
        await self.on_nexus_ready()
        await self.on_mineral_field_depleted()

    async def step_scouting_workers(self):
        if self.bot.units.not_structure.filter(
            lambda x: x.type_id not in self.worker_unit_types
        ).amount > 0:
            self.scouting_workers = {}
            return

        self.update_scouting_worker_status()
        await self.get_more_scouting_workers()
        await self.micro_scouting_workers()

    async def micro_scouting_workers(self):
        for unit_tag in self.scouting_workers.keys():
            await self.micro_scouting_worker(unit_tag)

    async def micro_scouting_worker(self, unit_tag):
        unit = self.bot.units.find_by_tag(unit_tag)
        info = self.scouting_workers[unit_tag]

        if unit.is_idle:
            target = self.get_scouting_position(unit_tag)
            info['target'] = target
            await self.bot.do(unit.move(target))
        elif info['new']:
            info['new'] = False
        else:
            if self.bot.known_enemy_units.amount == 0:
                return

            threats = self.bot.known_enemy_units.filter(
                lambda x: x.can_attack_ground and
                x.type_id not in self.worker_unit_types
            )

            if not threats.exists:
                return

            closest_unit = threats.closest_to(unit.position)

            if closest_unit is None:
                return

            distance_to_clostest_unit = unit.position.distance_to(
                closest_unit.position
            ) - unit.radius - closest_unit.radius

            if distance_to_clostest_unit < closest_unit.ground_range + 1.0:
                step_back_position = unit.position.towards(
                    closest_unit.position,
                    -1
                )
                await self.bot.do(unit.move(step_back_position))
            else:
                await self.bot.do(unit.move(info['target']))

    def get_scouting_position(self, unit_tag):
        info = self.scouting_workers[unit_tag]
        unit = self.bot.units.find_by_tag(unit_tag)

        if info['mode'] == 'global':
            if len(self.scouting_queue) == 0:
                self.scouting_queue = list(self.bot.expansion_locations.keys())

            target = unit.position.closest(self.scouting_queue)
            self.scouting_queue.pop(self.scouting_queue.index(target))
        elif info['mode'] == 'near':
            if 'scouting_queue' not in info:
                info['scouting_queue'] = []

            if len(info['scouting_queue']) == 0:
                info['scouting_queue'] = list(
                    self.bot.expansion_locations.keys()
                )

                nexi = self.bot.units(UnitTypeId.NEXUS).ready

                ignore = []

                for nexus in nexi:
                    for target in info['scouting_queue']:
                        if nexus.position.distance_to(Point2(target)) <= 5:
                            ignore.append(target)

                for target in ignore:
                    info['scouting_queue'].pop(info['scouting_queue'].index(
                        target)
                    )

                info['scouting_queue'].sort(key=lambda x: self.bot.start_location.distance_to(Point2(x)))
                info['scouting_queue'] = info['scouting_queue'][:self.number_of_near_expansions_to_scout]

            target = unit.position.closest(info['scouting_queue'])
            info['scouting_queue'].pop(info['scouting_queue'].index(target))

        return target

    def update_scouting_worker_status(self):
        dead_scouts = []

        for unit_tag in self.scouting_workers.keys():
            if self.bot.units.find_by_tag(unit_tag) is None:
                dead_scouts.append(unit_tag)

        for unit_tag in dead_scouts:
            self.scouting_workers.pop(unit_tag)

    async def get_more_scouting_workers(self):
        if len(self.scouting_workers) < self.number_of_scouting_workers:
            number_of_global_scouts = len(
                list(
                    filter(
                        lambda x: x['mode'] == 'global',
                        self.scouting_workers.values()
                    )
                )
            )
            number_of_near_scouts = len(
                list(
                    filter(
                        lambda x: x['mode'] == 'near',
                        self.scouting_workers.values()
                    )
                )
            )

            probes = self.bot.units(UnitTypeId.PROBE)

            if probes.exists:
                new_scouting_probe = probes.first

                if number_of_near_scouts < self.number_of_near_scouts:
                    self.scouting_workers[new_scouting_probe.tag] = {
                        'mode': 'near',
                        'new': True
                    }
                elif number_of_global_scouts < self.number_of_global_scouts:
                    self.scouting_workers[new_scouting_probe.tag] = {
                        'mode': 'global',
                        'new': True
                    }
                else:
                    self.scouting_workers[new_scouting_probe.tag] = {
                        'mode': 'global',
                        'new': True
                    }

                await self.bot.do(new_scouting_probe.stop())

    async def step_militia_workers(self):
        self.update_militia()
        await self.micro_militia()

    def update_militia(self):
        for enemy_tag, info in self.nearby_enemy_workers_found.items():
            if 'attacking_units' not in info.keys():
                info['attacking_units'] = {}

            to_delete = []
            for unit_tag in info['attacking_units'].keys():
                if self.bot.units.find_by_tag(unit_tag) is None:
                    to_delete.append(unit_tag)

            for unit_tag in to_delete:
                info['attacking_units'].pop(unit_tag)

            militia_lacking = (
                len(info['attacking_units']) -
                self.number_of_units_to_attack_enemy_workers
            )

            for _ in range(militia_lacking):
                new = self.get_workers_for_militia()
                info['attacking_units'][new] = {'target': enemy_tag}

    async def micro_militia(self):
        for enemy_tag, info in self.nearby_enemy_workers_found.items():
            enemy = self.bot.known_enemy_units.find_by_tag(enemy_tag)

            if enemy is None:
                return

            for unit_tag in info['attacking_units']:
                unit = self.bot.units.find_by_tag(unit_tag)
                await self.bot.do(unit.attack(enemy))

    def get_workers_for_militia(self):
        for worker in self.bot.units(UnitTypeId.PROBE).gathering:
            if worker.tag not in self.militia.keys():
                self.militia[worker.tag] = {}
                return worker.tag

    def update_threats(self):
        # nexi = self.bot.units(UnitTypeId.NEXUS)

        nearby_enemy_workers = []
        nearby_enemy_units = []
        nearby_enemy_structures = []

        # for nexus in nexi:
        #     nearby_enemy_workers = self.bot.known_enemy_units.filter(
        #         lambda unit: unit.type_id in self.worker_unit_types
        #     ).closer_than(self.threat_proximity, nexus.position)

        #     nearby_enemy_units = self.bot.known_enemy_units.filter(
        #         lambda unit: unit.type_id not in self.worker_unit_types
        #     ).closer_than(self.threat_proximity, nexus.position)

        #     nearby_enemy_structures = self.bot.known_enemy_structures.closer_than(
        #         self.threat_proximity, nexus.position
        #     )

        nearby_enemy_workers = self.bot.known_enemy_units.filter(
            lambda unit: unit.type_id in self.worker_unit_types
        )

        nearby_enemy_units = self.bot.known_enemy_units.filter(
            lambda unit: unit.type_id not in self.worker_unit_types
        )

        nearby_enemy_structures = self.bot.known_enemy_structures

        for unit in nearby_enemy_workers:
            if unit.tag not in self.nearby_enemy_workers_found:
                self.nearby_enemy_workers_found[unit.tag] = {'position': unit.position}

        for unit in nearby_enemy_units:
            if unit.tag not in self.nearby_enemy_workers_found:
                self.nearby_enemy_workers_found[unit.tag] = {'position': unit.position}

        for unit in nearby_enemy_structures:
            if unit.tag not in self.nearby_enemy_structures_found:
                self.nearby_enemy_structures_found[unit.tag] = {'position': unit.position}

    def update_worker_count_on_gas(self):
        self.current_workers_on_gas = 0

        for geyser in self.bot.geysers:
            self.current_workers_on_gas += geyser.assigned_harvesters

    async def build_workers(self):
        if not self.auto_build_worker and not self.bot.coordinator.can('build'):
            return

        nexus = self.bot.units(UnitTypeId.NEXUS).ready.noqueue
        n_workers = self.bot.units(UnitTypeId.PROBE).amount

        if nexus.exists and n_workers < self.bot.units(UnitTypeId.NEXUS).amount * 22 and \
           n_workers < self.maximum_workers:
            if self.bot.can_afford(UnitTypeId.PROBE) and self.bot.supply_left >= 1:
                await self.bot.do(nexus.random.train(UnitTypeId.PROBE))

    async def handle_idle_workers(self):
        if not self.auto_handle_idle_workers:
            return

        idle_workers = self.bot.units(UnitTypeId.PROBE).idle.filter(
            lambda unit: unit.tag not in self.scouting_workers
        )

        if idle_workers.amount == 0 or self.bot.units(UnitTypeId.NEXUS).amount == 0:
            return

        owned_expansions = self.bot.owned_expansions

        new_idle_workers = 0

        for worker in idle_workers:
            if worker.tag not in self.idle_workers.keys():
                self.idle_workers[worker.tag] = {}
                new_idle_workers += 1

            send_to = None

            for priority in self.priority:
                if priority == 'GAS' and self.current_workers_on_gas < self.max_workers_on_gas:
                    for geyser in self.bot.geysers:
                        actual = geyser.assigned_harvesters
                        ideal = geyser.ideal_harvesters
                        missing = ideal - actual

                        if missing > 0 and send_to is None:
                            send_to = geyser
                            break
                else:
                    for _, townhall in owned_expansions.items():
                        actual = townhall.assigned_harvesters
                        ideal = townhall.ideal_harvesters
                        missing = ideal - actual

                        if missing > 0 and send_to is None:
                            mineral = self.get_mineral_for_townhall(townhall)
                            send_to = mineral
                            break

            await self.bot.do(worker.gather(send_to))

        if self.verbose and new_idle_workers > 0:
            print('%8.2f %3d Found %d idle workers' % (self.bot.time, self.bot.supply_used, new_idle_workers))

    async def on_nexus_ready(self):
        for nexus in self.bot.units(UnitTypeId.NEXUS).ready:
            if nexus.tag not in self.nexus.keys():
                self.nexus[nexus.tag] = {}
                for event in self.on_nexus_ready_do:
                    await event()

    async def on_mineral_field_depleted(self):
        if self.bot.time - self.mineral_field_count_timer > self.mineral_field_count_cooldown:
            self.mineral_field_count_timer = self.bot.time
            mineral_field_count = sum([
                self.bot.state.mineral_field.closer_than(10, x).amount
                for x in self.bot.townhalls
            ])

            if mineral_field_count < self.mineral_field_count:
                for event in self.on_mineral_field_depleted_do:
                    await event()

            self.mineral_field_count = mineral_field_count

    def get_mineral_for_townhall(self, townhall):
        townhall_tag = townhall.tag

        if townhall_tag in self.mineral_field_cache.keys():
            mineral = self.mineral_field_cache[townhall_tag]
            if self.bot.units.find_by_tag(mineral.tag) is not None:
                return mineral

        mineral = self.bot.state.mineral_field.closest_to(townhall)
        self.mineral_field_cache[townhall_tag] = mineral

        return mineral

    async def redistribute_workers(self):
        """
        Taken from https://github.com/Dentosal/python-sc2/blob/master/sc2/bot_ai.py
        Distributes workers across all the bases taken.
        WARNING: This is quite slow when there are lots of workers or multiple bases.
        """

        # TODO:
        # OPTIMIZE: Assign idle workers smarter
        # OPTIMIZE: Never use same worker mutltiple times

        owned_expansions = self.bot.owned_expansions
        worker_pool = []
        for idle_worker in self.bot.workers.idle:
            mf = self.bot.state.mineral_field.closest_to(idle_worker)
            await self.bot.do(idle_worker.gather(mf))

        for location, townhall in owned_expansions.items():
            workers = self.bot.workers.closer_than(20, location)
            actual = townhall.assigned_harvesters
            ideal = townhall.ideal_harvesters
            excess = actual - ideal
            if actual > ideal:
                worker_pool.extend(workers.random_group_of(min(excess, len(workers))))
                continue
        for g in self.bot.geysers:
            workers = self.bot.workers.closer_than(5, g)
            actual = g.assigned_harvesters
            ideal = g.ideal_harvesters
            excess = actual - ideal
            if actual > ideal:
                worker_pool.extend(workers.random_group_of(min(excess, len(workers))))
                continue

        for g in self.bot.geysers:
            actual = g.assigned_harvesters
            ideal = g.ideal_harvesters
            deficit = ideal - actual

            for _ in range(0, deficit):
                if worker_pool:
                    w = worker_pool.pop()
                    if len(w.orders) == 1 and w.orders[0].ability.id in [AbilityId.HARVEST_RETURN]:
                        await self.bot.do(w.move(g))
                        await self.bot.do(w.return_resource(queue=True))
                    else:
                        await self.bot.do(w.gather(g))

        for location, townhall in owned_expansions.items():
            actual = townhall.assigned_harvesters
            ideal = townhall.ideal_harvesters

            deficit = ideal - actual
            for _ in range(0, deficit):
                if worker_pool:
                    w = worker_pool.pop()
                    mf = self.bot.state.mineral_field.closest_to(townhall)
                    if len(w.orders) == 1 and w.orders[0].ability.id in [AbilityId.HARVEST_RETURN]:
                        await self.bot.do(w.move(townhall))
                        await self.bot.do(w.return_resource(queue=True))
                        await self.bot.do(w.gather(mf, queue=True))
                    else:
                        await self.bot.do(w.gather(mf))

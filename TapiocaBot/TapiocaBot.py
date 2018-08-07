from patch_path import patch_path
patch_path()
import numpy as np
import random
import sys
import sc2
from sc2 import Race, Difficulty
from sc2.constants import *
from sc2.player import Bot, Computer
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3

from event_manager import EventManager
from army_manager import ArmyManager
from build_order_manager import BuildOrderManager
from robotics_facility_controller import RoboticsFacilitiyController
from gateway_controller import GatewayController
from scouting_controller import ScoutingController


class TapiocaBot(sc2.BotAI):
    def __init__(self):
        self.verbose = True
        self.visual_debug = False

        # Control Stuff
        self.want_to_expand = False
        self.researched_warpgate = False

        # Attack stuff
        self.army_manager = ArmyManager(bot=self)
        self.attack_target = None
        self.units_available_for_attack = {ZEALOT: 'ZEALOT', STALKER: 'STALKER'}
        self.minimum_army_size = 15

        # Defense stuff
        self.threat_proximity = 20
        self.defending_units = {}
        self.defend_around = [PYLON, NEXUS]

        # Threat stuff stuff
        self.defending_from = {}

        # Expansion and macro stuff
        self.auto_expand_after = 60 * 6.5
        self.auto_expand_mineral_threshold = 22 # Should be 2.5 ~ 3 fully saturated bases
        self.maximum_workers = 66
        self.gateways_per_nexus = 2
        self.chronos_on_nexus = 0
        self.warpgate_started = False
        self.adepts_warped_in = 0
        self.stalkers_warped_in = 0

        # Research stuff
        self.start_forge_after = 240  # seconds - 4min
        self.forge_research_priority = ['ground_weapons', 'shield']

        # Managers and controllers
        self.scouting_controller = ScoutingController(bot=self, verbose=self.verbose)
        self.robotics_facility_controller = RoboticsFacilitiyController(bot=self, verbose=self.verbose)
        self.gateway_controller = GatewayController(bot=self, verbose=self.verbose, auto_morph_to_warpgate=False)
        self.event_manager = EventManager()
        self.build_order_manager = BuildOrderManager(
            build_order='two_gate_fast_expand',
            verbose=self.verbose,
            bot=self
        )

        self.upgrades = {
            'ground_weapons': [
                FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL1,
                FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL2,
                FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL3],
            'ground_armor': [
                FORGERESEARCH_PROTOSSGROUNDARMORLEVEL1,
                FORGERESEARCH_PROTOSSGROUNDARMORLEVEL2,
                FORGERESEARCH_PROTOSSGROUNDARMORLEVEL3],
            'shield' : [
                FORGERESEARCH_PROTOSSSHIELDSLEVEL1,
                FORGERESEARCH_PROTOSSSHIELDSLEVEL2,
                FORGERESEARCH_PROTOSSSHIELDSLEVEL3]
            }

        self.upgrade_names = {
                FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL1: 'GROUND WEAPONS 1',
                FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL2: 'GROUND WEAPONS 2',
                FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL3: 'GROUND WEAPONS 2',
                FORGERESEARCH_PROTOSSGROUNDARMORLEVEL1: 'GROUND ARMOR 2',
                FORGERESEARCH_PROTOSSGROUNDARMORLEVEL2: 'GROUND ARMOR 2',
                FORGERESEARCH_PROTOSSGROUNDARMORLEVEL3: 'GROUND ARMOR 2',
                FORGERESEARCH_PROTOSSSHIELDSLEVEL1: 'SHIELDS 1',
                FORGERESEARCH_PROTOSSSHIELDSLEVEL2: 'SHIELDS 2',
                FORGERESEARCH_PROTOSSSHIELDSLEVEL3: 'SHIELDS 3'
            }

    def on_start(self):
        self.army_manager.init()

        # TODO Tweak these values
        self.event_manager.add_event(self.distribute_workers, 10)
        self.event_manager.add_event(self.handle_idle_workders, 0.5)
        #self.event_manager.add_event(self.manage_upgrades, 5.3)
        #self.event_manager.add_event(self.build_assimilator, 2.5)
        #self.event_manager.add_event(self.build_structures, 2.4)
        #self.event_manager.add_event(self.build_army, 0.9)
        #self.event_manager.add_event(self.scout_controller, 7)
        #self.event_manager.add_event(self.army_controller, 1.1)
        self.event_manager.add_event(self.defend, 1)
        #self.event_manager.add_event(self.attack, 3)
        self.event_manager.add_event(self.build_order_manager.step, 0.5)

    async def on_step(self, iteration):
        sys.stdout.flush()

        if iteration == 0:  # Do nothing on the first iteration to avoid
                            # everything being done at the same time
            if self.verbose:
                print('\n------------------------\n')
                print('%8.2f %3d Rise and Shine' % (self.time, self.supply_used))

            return

        if self.build_order_manager.did_early_game_just_end():
            print('             Enabling more stuff')
            self.event_manager.add_event(self.manage_supply, 1)
            self.event_manager.add_event(self.expansion_controller, 5)
            self.event_manager.add_event(self.build_nexus, 5)
            self.event_manager.add_event(self.build_workers, 2.25)
            self.event_manager.add_event(self.scouting_controller.step, 10)

            # Gateway stuff
            self.event_manager.add_event(self.gateway_controller.step, 1.0)
            self.gateway_controller.add_order((SENTRY, 1))
            self.gateway_controller.add_order((STALKER, 3))
            self.gateway_controller.add_order((ZEALOT, 2))
            self.gateway_controller.add_order((ADEPT, 1))

            # Robo stuff
            self.event_manager.add_event(self.robotics_facility_controller.step, 1.0)

            self.robotics_facility_controller.add_order(OBSERVER)
            self.robotics_facility_controller.add_order(IMMORTAL)
            self.robotics_facility_controller.add_order(IMMORTAL)
            self.robotics_facility_controller.add_order(IMMORTAL)

        events = self.event_manager.get_current_events(self.time)
        for event in events:
            await event()

        await self.debug()

    async def expansion_controller(self):
        if self.time > self.auto_expand_after:
            number_of_minerals = sum([self.state.mineral_field.closer_than(10, x).amount for x in self.townhalls])

            if number_of_minerals <= self.auto_expand_mineral_threshold:
                self.want_to_expand = True

    async def army_controller(self):
        await self.army_manager.step()

    async def defend(self):
        # Attacks units that get too close to import units
        for structure_type in self.defend_around:
            for structure in self.units(structure_type):
                threats = self.known_enemy_units.closer_than(self.threat_proximity, structure.position)
                if threats.exists:
                    target_threat = None
                    new_threat_count = 0

                    for threat in threats:
                        if threat.tag not in self.defending_from:
                            self.defending_from[threat.tag] = None
                            target_threat = threat
                            new_threat_count += 1

                    if new_threat_count > 0:
                        if self.verbose:
                            print('%6.2f found %d threats' % (self.time, new_threat_count))
                        await self.target_enemy_unit(target_threat)
                        break

    async def target_enemy_unit(self, target):
        # sends all idle units to attack an enemy unit

        zealots = self.units(ZEALOT).idle
        stalkers = self.units(STALKER).idle
        total_units = zealots.amount + stalkers.amount

        # Only sends 1 unit to attack a worker
        is_worker = target.type_id in [PROBE, SCV, DRONE]

        if self.verbose:
            print('%6.2f defending with %d units' % (self.time, total_units))

        for unit_group in [zealots, stalkers]:
            for unit in unit_group:
                if is_worker:
                    await self.do(unit.attack(target))
                    if self.verbose:
                        print('     - target is a probe, sending a single unit')
                    return
                else:
                    await self.do(unit.attack(target.position))

    async def attack(self):
        total_units = 0
        for unit_type in self.units_available_for_attack.keys():
            total_units += self.units(unit_type).idle.amount

        if total_units >= self.minimum_army_size:
            if self.army_manager.army_size() == 0:
                for unit_type in self.units_available_for_attack.keys():
                    for unit in self.units(unit_type).idle:
                        self.army_manager.add(unit.tag)

                await self.army_manager.group_at_map_center(wait_for_n_units=total_units - 1, timeout=30, move_towards_position=self.enemy_start_locations[0])

                if self.verbose:
                    print('%6.2f Attacking with %d units' % (self.time, total_units))
            else:
                for unit_type in self.units_available_for_attack.keys():
                    for unit in self.units(unit_type).idle:
                        self.army_manager.add(unit.tag, options={'reinforcement': True})

                if self.verbose:
                    print('%6.2f reinforcing with %d units' % (self.time, total_units))

    async def build_army(self):
        if not self.can('build_army'):
            return

        # Iterates over all gateways
        for gateway in self.units(GATEWAY).ready.noqueue:
            abilities = await self.get_available_abilities(gateway)

            # Checks if the gateway can morph into a warpgate
            if AbilityId.MORPH_WARPGATE in abilities and self.can_afford(AbilityId.MORPH_WARPGATE):
                await self.do(gateway(MORPH_WARPGATE))

            # Else, tries to build a stalker
            elif AbilityId.GATEWAYTRAIN_STALKER in abilities:
                if self.can_afford(STALKER) and self.supply_left > 2:
                    await self.do(gateway.train(STALKER))

            # Else, tries to build a zealot
            elif AbilityId.GATEWAYTRAIN_ZEALOT in abilities:
                if self.can_afford(ZEALOT) and self.supply_left > 2:
                    await self.do(gateway.train(ZEALOT))

        # Iterates over all warpgates and warp in stalkers
        for warpgate in self.units(WARPGATE).ready:
            abilities = await self.get_available_abilities(warpgate)
            if AbilityId.WARPGATETRAIN_ZEALOT in abilities:
                if self.can_afford(STALKER) and self.supply_left > 2:
                    # Smartly find a good pylon boy to warp in units next to it
                    pylon = self.pylon_with_less_units()
                    pos = pylon.position.to2.random_on_distance(4)
                    placement = await self.find_placement(AbilityId.WARPGATETRAIN_STALKER, pos, placement_step=1)

                    if placement:
                        await self.do(warpgate.warp_in(STALKER, placement))
                    else:
                        # otherwise just brute force it
                        for _ in range(10):  # TODO tweak this
                            pylon = self.units(PYLON).ready.random
                            pos = pylon.position.to2.random_on_distance(4)
                            placement = await self.find_placement(AbilityId.WARPGATETRAIN_STALKER, pos, placement_step=1)

                            if placement is None:
                                if self.verbose:
                                    print("%6.2f can't place" % (self.time))
                                return

                            await self.do(warpgate.warp_in(STALKER, placement))
                            continue

    async def build_structures(self):
        if not self.can('build_structures'):
            return

        # Only start building main structures if there is
        # at least one pylon
        if not self.units(PYLON).ready.exists:
            return
        else:
            pylon = self.units(PYLON).ready.random

        number_of_gateways = self.units(WARPGATE).amount + self.units(GATEWAY).amount

        # Build the first gateway
        if self.can_afford(GATEWAY) and number_of_gateways == 0:
            if self.verbose:
                print('%6.2f starting first gateway' % (self.time))
            await self.build(GATEWAY, near=pylon)

        # Build the cybernetics core after the first gateway is ready
        if self.can_afford(CYBERNETICSCORE) and self.units(CYBERNETICSCORE).amount == 0 and self.units(GATEWAY).ready:
            if self.verbose:
                print('%6.2f starting cybernetics' % (self.time))
            await self.build(CYBERNETICSCORE, near=pylon)
            self.want_to_expand = True

        # Build more gateways after the cybernetics core is ready
        if self.can_afford(GATEWAY) and self.units(CYBERNETICSCORE).ready and (
                (number_of_gateways < 4 and self.units(NEXUS).amount <= 2) or
                (number_of_gateways <= self.units(NEXUS).amount * self.gateways_per_nexus)
            ):
            if self.verbose:
                print('%6.2f starting more gateways' % (self.time))
            await self.build(GATEWAY, near=pylon)

        # Build 2 forges
        if self.time > self.start_forge_after and self.units(FORGE).amount < 2:
            if self.can_afford(FORGE) and not self.already_pending(FORGE):
                if self.verbose:
                    print('%6.2f building forge' % (self.time))
                await self.build(FORGE, near=pylon)

        # Build twilight council
        if self.units(FORGE).ready.amount >= 2 and self.units(TWILIGHTCOUNCIL).amount == 0:
            if self.can_afford(TWILIGHTCOUNCIL) and not self.already_pending(TWILIGHTCOUNCIL):
                if self.verbose:
                    print('%6.2f building twilight council' % (self.time))
                await self.build(TWILIGHTCOUNCIL, near=pylon)

    async def build_nexus(self):
        if not self.can('expand'):
            return

        if not self.already_pending(NEXUS) and self.can_afford(NEXUS):
            if self.verbose:
                print('%6.2f expanding' % (self.time))

            await self.expand_now()
            self.want_to_expand = False

    async def manage_upgrades(self):
        await self.manage_cyberbetics_upgrades()
        await self.manage_forge_upgrades()

    async def manage_cyberbetics_upgrades(self):
        if self.units(CYBERNETICSCORE).ready.exists and self.can_afford(RESEARCH_WARPGATE) and not self.researched_warpgate:
            ccore = self.units(CYBERNETICSCORE).ready.first
            await self.do(ccore(RESEARCH_WARPGATE))
            self.researched_warpgate = True

            if self.verbose:
                print('%6.2f researching warpgate' % (self.time))

    async def manage_forge_upgrades(self):
        for forge in self.units(FORGE).ready.noqueue:
            abilities = await self.get_available_abilities(forge)

            for upgrade_type in self.forge_research_priority:
                for upgrade in self.upgrades[upgrade_type]:
                    sys.stdout.flush()
                    if upgrade in abilities and self.can_afford(upgrade):
                        if self.verbose:
                            print('%6.2f researching %s' % (self.time, self.upgrade_names[upgrade]))

                        await self.do(forge(upgrade))
                        break

    async def build_workers(self):
        nexus = self.units(NEXUS).ready.noqueue

        if nexus and self.workers.amount < self.units(NEXUS).amount * 22 and self.workers.amount < self.maximum_workers:
            if self.can_afford(PROBE) and self.supply_left > 2:
                await self.do(nexus.random.train(PROBE))

    async def handle_idle_workders(self):
        idle_workers = self.units(PROBE).idle

        if idle_workers.exists:
            await self.distribute_workers()

    async def build_pylon(self):
        for tries in range(5):  # Only tries 5 different placements
            nexus = self.units(NEXUS).ready

            if not nexus.exists:
                return

            nexus = nexus.random

            if not self.already_pending(PYLON) and self.can_afford(PYLON):
                pos = await self.find_placement(PYLON, nexus.position, placement_step=2)
                mineral_fields = self.state.mineral_field.closer_than(12, nexus).closer_than(4, pos)

                if mineral_fields:
                    continue
                else:
                    await self.build(PYLON, near=pos)
                    break

    async def manage_supply(self):
        for tries in range(5):  # Only tries 5 different placements
            nexus = self.units(NEXUS).ready

            if not nexus:
                return

            nexus = nexus.random

            if self.supply_left < 8 and not self.already_pending(PYLON):
                if self.can_afford(PYLON):
                    pos = await self.find_placement(PYLON, nexus.position, placement_step=2)
                    mineral_fields = self.state.mineral_field.closer_than(8, nexus).closer_than(4, pos)

                    if mineral_fields:
                        continue
                    else:
                        await self.build(PYLON, near=pos)
                        break

    async def build_assimilator(self):
        for nexus in self.units(NEXUS).ready:
            vgs = self.state.vespene_geyser.closer_than(15, nexus)
            for vg in vgs:
                worker = self.select_build_worker(vg.position)
                if worker is None:
                    break

                if not self.units(ASSIMILATOR).closer_than(1.0, vg).exists and self.can_afford(ASSIMILATOR):
                    await self.do(worker.build(ASSIMILATOR, vg))

    async def debug(self):
        if not self.visual_debug:
            return

        # Setup and info

        font_size = 18

        total_units = 0
        for unit_type in self.units_available_for_attack.keys():
            total_units += self.units(unit_type).idle.amount

        number_of_minerals = sum([self.state.mineral_field.closer_than(10, x).amount for x in self.townhalls])

        # Text

        messages = [
            '       n_workers: %3d' % self.units(PROBE).amount,
            '       n_zealots: %3d' % self.units(ZEALOT).amount,
            '      n_stalkers: %3d' % self.units(STALKER).amount,
            '       idle_army: %3d' % total_units,
            '       army_size: %3d' % self.army_manager.army_size(),
            '     ememy_units: %3d' % self.known_enemy_units.amount,
            'ememy_structures: %3d' % self.known_enemy_structures.amount,
            '   minerals_left: %3d' % number_of_minerals,
        ]

        if self.army_manager.leader is not None:
            messages.append('     leader: %3d' % self.army_manager.leader)

        y = 0
        inc = 0.025

        for message in messages:
            self._client.debug_text_screen(message, pos=(0.001, y), size=font_size)
            y += inc

        # Spheres

        leader_tag = self.army_manager.leader
        for soldier_tag in self.army_manager.soldiers:
            soldier_unit = self.units.find_by_tag(soldier_tag)

            if soldier_unit is not None:
                if soldier_tag == leader_tag:
                    self._client.debug_sphere_out(soldier_unit, r=1, color=(255, 0, 0))
                else:
                    self._client.debug_sphere_out(soldier_unit, r=1, color=(0, 0, 255))

        # Lines

        if self.army_manager.army_size() > 0:
            leader_tag = self.army_manager.leader
            leader_unit = self.units.find_by_tag(leader_tag)

            for soldier_tag in self.army_manager.soldiers:
                if soldier_tag == leader_tag:
                    continue

                soldier_unit = self.units.find_by_tag(soldier_tag)
                if soldier_unit is not None:
                    leader_tag = self.army_manager.leader
                    leader_unit = self.units.find_by_tag(leader_tag)
                    if leader_unit is not None:
                        self._client.debug_line_out(leader_unit, soldier_unit, color=(0, 255, 255))

        # Sens the debug info to the game
        await self._client.send_debug()

    def select_target(self, state):
        if self.known_enemy_structures.exists:
            return random.choice(self.known_enemy_structures)

        return self.enemy_start_locations[0]

    # Finds the pylon with more "space" next to it
    # Where more space == Less units
    # TODO consider "warpable" space
    def pylon_with_less_units(self, distance=4):
        pylons = self.units(PYLON).ready

        good_boy_pylon = None
        units_next_to_good_boy_pylon = float('inf')

        for pylon in pylons:
            units_next_to_candidate_pylon = self.units.closer_than(distance, pylon).amount

            if units_next_to_candidate_pylon < units_next_to_good_boy_pylon:
                good_boy_pylon = pylon
                units_next_to_good_boy_pylon = units_next_to_candidate_pylon

        return good_boy_pylon

    def can(self, what):
        if what == 'build_army':
            return not self.want_to_expand

        if what == 'build_structures':
            return not self.want_to_expand

        if what == 'build_assimilator':
            return not self.want_to_expand

        if what == 'expand':
            return self.want_to_expand

        self.console()

    def console(self):
        from IPython.terminal.embed import InteractiveShellEmbed
        ipshell = InteractiveShellEmbed.instance()
        ipshell()

    def get_unit_info(self, unit, field="food_required"):
        assert isinstance(unit, (Unit, UnitTypeId))

        if isinstance(unit, Unit):
            unit = unit._type_data._proto
        else:
            unit = self._game_data.units[unit.value]._proto

        if hasattr(unit, field):
            return getattr(unit, field)
        else:
            return None

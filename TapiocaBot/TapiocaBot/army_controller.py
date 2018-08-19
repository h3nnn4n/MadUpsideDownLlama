import random
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId


class ArmyController:
    def __init__(self, bot=None, verbose=False):
        self.bot = bot
        self.verbose = verbose

        self.auto_recuit = True
        self.attack_when_maxed_out = True
        self.minimum_army_size = 40
        self.attack_trigger_radius = 7
        self.stop_radius = 5
        self.units_available_for_attack = {
            UnitTypeId.ZEALOT: 'ZEALOT',
            UnitTypeId.ADEPT: 'ADEPT',
            UnitTypeId.SENTRY: 'SENTRY',
            UnitTypeId.STALKER: 'STALKER',
            UnitTypeId.IMMORTAL: 'IMMORTAL',
        }

        self.defend_around = [UnitTypeId.PYLON, UnitTypeId.NEXUS]
        self.threat_proximity = 20

        self.distance_timer = 2.5  # Time between distance checks
        self.send_attack_timer = 0
        self.resend_to_center_timer = 0
        self.units_to_ignore_defending = [
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERSEER,
            UnitTypeId.OVERSEERSIEGEMODE,
            UnitTypeId.PROBE,
            UnitTypeId.SCV,
            UnitTypeId.DRONE,
            UnitTypeId.OBSERVER,
            UnitTypeId.OBSERVERSIEGEMODE,
            UnitTypeId.CHANGELING,
            UnitTypeId.CHANGELINGZEALOT,
            UnitTypeId.CHANGELINGMARINESHIELD,
            UnitTypeId.CHANGELINGMARINE,
            UnitTypeId.CHANGELINGZERGLINGWINGS,
            UnitTypeId.CHANGELINGZERGLING,
            UnitTypeId.EGG,
            UnitTypeId.OBSERVER,
            UnitTypeId.INTERCEPTOR,
            UnitTypeId.CREEPTUMOR,
            UnitTypeId.CREEPTUMORBURROWED,
            UnitTypeId.CREEPTUMORQUEEN,
            UnitTypeId.CREEPTUMORMISSILE
        ]

        self.units_to_ignore_attacking = [
            UnitTypeId.CHANGELING,
            UnitTypeId.CHANGELINGZEALOT,
            UnitTypeId.CHANGELINGMARINESHIELD,
            UnitTypeId.CHANGELINGMARINE,
            UnitTypeId.CHANGELINGZERGLINGWINGS,
            UnitTypeId.CHANGELINGZERGLING,
            UnitTypeId.EGG,
            UnitTypeId.OBSERVER,
            UnitTypeId.CREEPTUMOR,
            UnitTypeId.CREEPTUMORBURROWED,
            UnitTypeId.CREEPTUMORQUEEN,
            UnitTypeId.CREEPTUMORMISSILE
        ]

        self.threats = None
        self.leader = None
        self.soldiers = {}
        self.attacking = False
        self.attack_target = None
        self.defense_target = None
        self.first_attack = True

    def init(self):
        self.map_center = self.bot.game_info.map_center

    async def step(self):
        self.auto_recuiter()
        await self.update_soldier()
        self.update_leader()

    def auto_recuiter(self):
        if not self.auto_recuit:
            return

        for unit_type in self.units_available_for_attack.keys():
            for unit in self.bot.units(unit_type).idle:
                if unit.tag not in self.soldiers:
                    self.add(unit.tag, {'state': 'new'})
                    if self.verbose:
                        print('   ->  Found new unit')

    def add(self, unit_tag, options={}):
        self.soldiers[unit_tag] = options

        if self.leader is None:
            self.leader = unit_tag

    def update_leader(self):
        if self.army_size() > 0:
            if self.leader not in self.soldiers:
                self.leader = next(iter(self.soldiers))

                if self.verbose:
                    print('%6.2f leader died, found new one' % (self.bot.time))
        else:
            self.leader = None

    def army_size(self):
        return len(self.soldiers)

    async def update_soldier(self):
        tags_to_delete = []

        # leader_tag, leader_unit = self.get_updated_leader()

        needs_to_defend = self.needs_to_defend()
        send_attack = self.can_attack()

        for soldier_tag in self.soldiers:
            soldier_unit = self.bot.units.find_by_tag(soldier_tag)

            if soldier_unit is None:
                tags_to_delete.append(soldier_tag)
            else:
                info = self.soldiers[soldier_tag]

                if needs_to_defend and info['state'] != 'attacking':
                    await self.send_defense(soldier_tag)

                if info['state'] == 'new':
                    await self.move_to_center(soldier_tag)
                elif info['state'] == 'moving_to_center':
                    await self.moving_to_center(soldier_tag)
                elif info['state'] == 'waiting_at_center':
                    if send_attack:
                        await self.send_attack(soldier_tag)
                    await self.waiting_at_center(soldier_tag)
                elif info['state'] == 'attacking':
                    await self.micro_unit(soldier_tag)
                elif info['state'] == 'defending':
                    await self.defend(soldier_tag)

        for tag in tags_to_delete:
            self.soldiers.pop(tag)

    def get_updated_leader(self):
        tag = self.leader
        unit = self.bot.units.find_by_tag(tag)

        return tag, unit

    def can_attack(self):
        if self.bot.time - self.send_attack_timer >= self.distance_timer:
            self.send_attack_timer = self.bot.time
            close_units = self.bot.units.closer_than(self.attack_trigger_radius, self.map_center)
            if close_units.amount >= self.minimum_army_size or \
               (self.attack_when_maxed_out and self.bot.supply_left < 3 and self.bot.supply_cap == 200):
                return True

        return False

    async def move_to_center(self, unit_tag):
        unit = self.bot.units.find_by_tag(unit_tag)

        # leader_tag, leader_unit = self.get_updated_leader()

        await self.bot.do(unit.attack(self.map_center))
        self.soldiers[unit_tag]['state'] = 'moving_to_center'
        self.soldiers[unit_tag]['distance_to_center_timer'] = self.bot.time

    async def moving_to_center(self, unit_tag):
        unit = self.bot.units.find_by_tag(unit_tag)

        if self.bot.time - self.soldiers[unit_tag]['distance_to_center_timer'] >= self.distance_timer:
            self.soldiers[unit_tag]['distance_to_center_timer'] = self.bot.time

            if unit.distance_to(self.map_center) < self.stop_radius:
                self.soldiers[unit_tag]['state'] = 'waiting_at_center'
                self.soldiers[unit_tag]['waiting_at_center_timer'] = self.bot.time
                self.soldiers[unit_tag]['resend_to_center_timer'] = self.bot.time
            else:
                await self.bot.do(unit.attack(self.map_center))

    async def waiting_at_center(self, unit_tag):
        unit = self.bot.units.find_by_tag(unit_tag)

        if self.number_of_attacking_units() > self.minimum_army_size / 2.0:
            self.soldiers[unit_tag]['state'] = 'attacking'
            await self.bot.do(unit.attack(self.attack_target))
        elif self.bot.time - self.soldiers[unit_tag]['resend_to_center_timer'] >= self.distance_timer:
            self.soldiers[unit_tag]['resend_to_center_timer'] = self.bot.time
            if unit.distance_to(self.map_center) > self.attack_trigger_radius:
                if self.attack_target is not None and self.number_of_attacking_units() > self.minimum_army_size:
                    self.soldiers[unit_tag]['state'] = 'attacking'
                    await self.bot.do(unit.attack(self.attack_target))
                else:
                    await self.bot.do(unit.attack(self.map_center))

    async def send_attack(self, unit_tag):
        unit = self.bot.units.find_by_tag(unit_tag)

        if self.attack_target is None:
            self.attack_target = self.get_something_to_attack()

        await self.bot.do(unit.attack(self.attack_target))

        self.soldiers[unit_tag]['state'] = 'attacking'

    async def send_defense(self, unit_tag):
        unit = self.bot.units.find_by_tag(unit_tag)
        self.soldiers[unit_tag]['state'] = 'defending'

        if self.defense_target is None:
            self.defense_target = self.get_new_threat_to_defend_from()

        if self.defense_target is not None:
            await self.bot.do(unit.attack(self.defense_target.position))

    async def micro_unit(self, unit_tag):
        unit = self.bot.units.find_by_tag(unit_tag)

        if unit.type_id == UnitTypeId.STALKER:
            await self.stalker_micro(unit_tag)
        else:
            if unit.is_idle:
                self.attack_target = self.get_something_to_attack()
                await self.bot.do(unit.attack(self.attack_target.position))

    async def stalker_micro(self, unit_tag):
        # self.bot._client.game_step = 2
        visual_debug = False
        font_size = 14

        unit = self.bot.units.find_by_tag(unit_tag)

        if self.bot.known_enemy_units.exclude_type(self.units_to_ignore_attacking).amount == 0:
            if unit.is_idle:
                self.attack_target = self.get_something_to_attack()
                await self.bot.do(unit.attack(self.attack_target.position))
            return

        all_enemy_units = self.bot.known_enemy_units.exclude_type(self.units_to_ignore_attacking)
        enemy_units = all_enemy_units.not_structure

        if enemy_units.exists:
            closest_unit = enemy_units.closest_to(unit)
        else:
            closest_unit = all_enemy_units.closest_to(unit)

        distance_to_closest_unit = unit.distance_to(closest_unit) - unit.radius / 2 - closest_unit.radius / 2 + 0.1

        step_back_position = unit.position.towards(closest_unit.position, -2)

        our_range = unit.ground_range + unit.radius
        enemy_range = closest_unit.ground_range + closest_unit.radius

        if visual_debug:
            self.bot._client.debug_sphere_out(unit, r=our_range, color=(0, 255, 255))
            self.bot._client.debug_sphere_out(closest_unit, r=enemy_range, color=(255, 0, 0))
            self.bot._client.debug_line_out(unit, closest_unit, color=(127, 127, 255))
            self.bot._client.debug_line_out(unit, step_back_position, color=(127, 0, 255))

        if unit.is_idle:
            self.attack_target = self.get_something_to_attack()
            await self.bot.do(unit.attack(self.attack_target.position))

            if visual_debug:
                self.bot._client.debug_text_world('cant see', pos=unit.position3d, size=font_size)
            return

        if our_range > enemy_range:  # Stalker outrange target
            if our_range < distance_to_closest_unit:  # But we are not in range
                if visual_debug:
                    self.bot._client.debug_text_world('too far', pos=unit.position3d, size=font_size)
                if unit.weapon_cooldown > 0:  # If weapon is on cool down we right click the unit
                    await self.bot.do(unit.attack(closest_unit))
                else:  # Else we right click the unit too
                    await self.bot.do(unit.attack(closest_unit))
            elif enemy_range + 0.1 < distance_to_closest_unit:  # They are in our range but we arent in theirs
                if closest_unit.is_structure:  # Get closer to structures
                    if visual_debug:
                        self.bot._client.debug_text_world('atk structure', pos=unit.position3d, size=font_size)
                    if unit.weapon_cooldown > 0 and distance_to_closest_unit > closest_unit.radius + 1:
                        advance_position = unit.position.towards(closest_unit.position, distance=1)
                        await self.bot.do(unit.move(advance_position))
                    else:
                        await self.bot.do(unit.attack(closest_unit))
                else:
                    if our_range - distance_to_closest_unit > 0.75:
                        step_back_position = unit.position.towards(closest_unit.position, -2)
                        if visual_debug:
                            self.bot._client.debug_text_world('closeish', pos=unit.position3d, size=font_size)
                        await self.bot.do(unit.move(step_back_position))
                    else:
                        if visual_debug:
                            self.bot._client.debug_text_world('ideal', pos=unit.position3d, size=font_size)
                        await self.bot.do(unit.attack(closest_unit))
            else:  # We are in their range but we can out range them
                # if unit.weapon_cooldown == 0:  # shoot first
                #     await self.bot.do(unit.attack(closest_unit))
                # else:
                #     distance = enemy_range - distance_to_closest_unit
                #     step_back_position = unit.position.towards(closest_unit.position, -distance)

                #     await self.bot.do(unit.move(step_back_position))
                # distance = enemy_range - distance_to_closest_unit

                abilities = await self.bot.get_available_abilities(unit)

                if unit.shield_percentage < 0.1 and AbilityId.EFFECT_BLINK_STALKER in abilities:
                    blink_back_position = unit.position.towards(closest_unit.position, -8)
                    await self.bot.do(unit(AbilityId.EFFECT_BLINK_STALKER, blink_back_position))
                else:
                    step_back_position = unit.position.towards(closest_unit.position, -1)
                    await self.bot.do(unit.move(step_back_position))

                if visual_debug:
                    self.bot._client.debug_text_world('too close', pos=unit.position3d, size=font_size)
        else:  # we either have the same range or we have less range
            abilities = await self.bot.get_available_abilities(unit)

            if unit.shield_percentage < 0.1 and AbilityId.EFFECT_BLINK_STALKER in abilities:
                blink_back_position = unit.position.towards(closest_unit.position, -8)
                await self.bot.do(unit(AbilityId.EFFECT_BLINK_STALKER, blink_back_position))
            else:
                if enemy_range >= distance_to_closest_unit:
                    if unit.shield_percentage < 0.1 and AbilityId.EFFECT_BLINK_STALKER in abilities:
                        blink_back_position = unit.position.towards(closest_unit.position, -8)
                        await self.bot.do(unit(AbilityId.EFFECT_BLINK_STALKER, blink_back_position))
                        if visual_debug:
                            self.bot._client.debug_text_world('blink', pos=unit.position3d, size=font_size)
                    else:
                        if unit.weapon_cooldown == 0:
                            await self.bot.do(unit.attack(closest_unit))
                            if visual_debug:
                                self.bot._client.debug_text_world('YOLO', pos=unit.position3d, size=font_size)
                        else:
                            step_back_position = unit.position.towards(closest_unit.position, -1)
                            await self.bot.do(unit.move(step_back_position))
                            if visual_debug:
                                self.bot._client.debug_text_world('back', pos=unit.position3d, size=font_size)

    async def defend(self, unit_tag):
        unit = self.bot.units.find_by_tag(unit_tag)

        if unit.is_idle:
            self.defense_target = self.get_new_threat_to_defend_from()

            if self.defense_target is None:
                self.soldiers[unit_tag]['state'] = 'new'
            else:
                await self.bot.do(unit.attack(self.defense_target.position))

    def get_something_to_attack(self):
        if self.bot.known_enemy_units.amount > 0:
            return self.bot.known_enemy_units.random

        if self.bot.known_enemy_structures.amount > 0:
            return self.bot.known_enemy_structures.random

        if self.first_attack:
            self.first_attack = False
            return self.bot.enemy_start_locations[0]

        return random.sample(list(self.bot.expansion_locations), k=1)[0]

    def get_new_threat_to_defend_from(self):
        for structure_type in self.defend_around:
            for structure in self.bot.units(structure_type):
                threats = self.bot.known_enemy_units.filter(
                    lambda unit: unit.type_id not in self.units_to_ignore_defending
                ).closer_than(self.threat_proximity, structure.position)

                if threats.exists:
                    return threats.random

        return None

    def number_of_attacking_units(self):
        count = 0

        for _, v in self.soldiers.items():
            if 'state' in v.keys() and v['state'] == 'attacking':
                count += 1

        return count

    def number_of_waiting_units(self):
        count = 0

        for _, v in self.soldiers.items():
            if 'state' in v.keys() and v['state'] == 'waiting':
                count += 1

        return count

    def needs_to_defend(self):
        new_threat = self.get_new_threat_to_defend_from()

        if new_threat is not None:
            return True

        return False

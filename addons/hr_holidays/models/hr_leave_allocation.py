# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

# Copyright (c) 2005-2006 Axelor SARL. (http://www.axelor.com)

import logging

from datetime import datetime, time
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.addons.resource.models.resource import HOURS_PER_DAY
from odoo.exceptions import AccessError, UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class HolidaysAllocation(models.Model):
    """ Allocation Requests Access specifications: similar to leave requests """
    _name = "hr.leave.allocation"
    _description = "Leaves Allocation"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _mail_post_access = 'read'

    def _default_employee(self):
        return self.env.context.get('default_employee_id') or self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)

    def _default_holiday_status_id(self):
        lt = self.env['hr.leave.type'].with_context(employee_id=self._default_employee().id).search([('valid', '=', True)], limit=1)
        return lt[:1]

    name = fields.Char('Description')
    state = fields.Selection([
        ('draft', 'To Submit'),
        ('cancel', 'Cancelled'),
        ('confirm', 'To Approve'),
        ('refuse', 'Refused'),
        ('validate1', 'Second Approval'),
        ('validate', 'Approved')
        ], string='Status', readonly=True, track_visibility='onchange', copy=False, default='confirm',
        help="The status is set to 'To Submit', when a leave request is created." +
        "\nThe status is 'To Approve', when leave request is confirmed by user." +
        "\nThe status is 'Refused', when leave request is refused by manager." +
        "\nThe status is 'Approved', when leave request is approved by manager.")
    date_from = fields.Datetime(
        'Start Date', readonly=True, index=True, copy=False,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]}, track_visibility='onchange')
    date_to = fields.Datetime(
        'End Date', readonly=True, copy=False,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]}, track_visibility='onchange')
    holiday_status_id = fields.Many2one(
        "hr.leave.type", string="Leave Type", required=True, readonly=True,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]},
        domain=[('valid', '=', True)], default=_default_holiday_status_id)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', index=True, readonly=True,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]}, default=_default_employee, track_visibility='onchange')
    notes = fields.Text('Reasons', readonly=True, states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]})
    number_of_days_temp = fields.Float(
        'Duration (days)', copy=False, readonly=True,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]},
        help='Number of days of the leave request according to your working schedule.')
    number_of_days = fields.Float('Number of Days', compute='_compute_number_of_days', store=True, track_visibility='onchange')
    number_of_hours = fields.Float('Duration (hours)', help="Number of hours of the leave allocation according to your working schedule.")
    parent_id = fields.Many2one('hr.leave.allocation', string='Parent')
    linked_request_ids = fields.One2many('hr.leave.allocation', 'parent_id', string='Linked Requests')
    first_approver_id = fields.Many2one(
        'hr.employee', string='First Approval', readonly=True, copy=False,
        help='This area is automatically filled by the user who validate the leave', oldname='manager_id')
    second_approver_id = fields.Many2one(
        'hr.employee', string='Second Approval', readonly=True, copy=False, oldname='manager_id2',
        help='This area is automaticly filled by the user who validate the leave with second level (If Leave type need second validation)')
    validation_type = fields.Selection('Validation Type', related='holiday_status_id.validation_type', readonly=True)
    can_reset = fields.Boolean('Can reset', compute='_compute_can_reset')
    can_approve = fields.Boolean('Can Approve', compute='_compute_can_approve')
    type_request_unit = fields.Selection(related='holiday_status_id.request_unit', readonly=True)
    # mode
    holiday_type = fields.Selection([
        ('employee', 'By Employee'),
        ('department', 'By Department'),
        ('category', 'By Employee Tag')],
        string='Allocation Mode', readonly=True, required=True, default='employee',
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]},
        help='By Employee: Allocation for individual Employee, By Employee Tag: Allocation for group of employees in category')
    department_id = fields.Many2one('hr.department', string='Department', readonly=True, states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]})
    category_id = fields.Many2one(
        'hr.employee.category', string='Employee Tag', readonly=True,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]}, help='Category of Employee')
    # accrual configuration
    accrual = fields.Boolean(
        "Accrual", readonly=True,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]})
    accrual_limit = fields.Integer('Balance limit', default=0, help="Maximum of allocation for accrual; 0 means no maximum.")
    number_per_interval = fields.Float("Number of unit per interval", readonly=True, states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]}, default=1)
    interval_number = fields.Integer("Number of unit between two intervals", readonly=True, states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]}, default=1)
    unit_per_interval = fields.Selection([
        ('hours', 'Hour(s)'),
        ('days', 'Day(s)')
        ], string="Unit of time added at each interval", default='hours', readonly=True, states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]})
    interval_unit = fields.Selection([
        ('weeks', 'Week(s)'),
        ('months', 'Month(s)'),
        ('years', 'Year(s)')
        ], string="Unit of time between two intervals", default='weeks', readonly=True, states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]})
    nextcall = fields.Date("Date of the next accrual allocation", default=False, readonly=True)

    _sql_constraints = [
        ('type_value', "CHECK( (holiday_type='employee' AND employee_id IS NOT NULL) or (holiday_type='category' AND category_id IS NOT NULL) or (holiday_type='department' AND department_id IS NOT NULL) )",
         "The employee, department or employee category of this request is missing. Please make sure that your user login is linked to an employee."),
        ('date_check', "CHECK ( number_of_days_temp >= 0 )", "The number of days must be greater than 0."),
        ('number_per_interval_check', "CHECK(number_per_interval > 0)", "The number per interval should be greater than 0"),
        ('interval_number_check', "CHECK(interval_number > 0)", "The interval number should be greater than 0"),
    ]

    @api.model
    def _update_accrual(self):
        """
            Method called by the cron task in order to increment the number_of_days when
            necessary.
        """
        today = fields.Date.from_string(fields.Date.today())

        holidays = self.search([('accrual', '=', True), ('state', '=', 'validate'),
                                '|', ('date_to', '=', False), ('date_to', '>', fields.Datetime.now()),
                                '|', ('nextcall', '=', False), ('nextcall', '<=', today)])

        for holiday in holidays:
            values = {}

            delta = relativedelta(days=0)

            if holiday.interval_unit == 'weeks':
                delta = relativedelta(weeks=holiday.interval_number)
            if holiday.interval_unit == 'months':
                delta = relativedelta(months=holiday.interval_number)
            if holiday.interval_unit == 'years':
                delta = relativedelta(years=holiday.interval_number)

            values['nextcall'] = (holiday.nextcall if holiday.nextcall else today) + delta

            period_start = datetime.combine(today, time(0, 0, 0)) - delta
            period_end = datetime.combine(today, time(0, 0, 0))

            # We have to check when the employee has been created
            # in order to not allocate him/her too much leaves
            creation_date = fields.Datetime.from_string(holiday.employee_id.create_date)

            # If employee is created after the period, we cancel the computation
            if period_end <= creation_date:
                holiday.write(values)
                continue

            # If employee created during the period, taking the date at which he has been created
            if period_start <= creation_date:
                period_start = creation_date

            worked = holiday.employee_id.get_work_days_data(period_start, period_end, domain=[('holiday_id.holiday_status_id.unpaid', '=', True), ('time_type', '=', 'leave')])['days']
            left = holiday.employee_id.get_leave_days_data(period_start, period_end, domain=[('holiday_id.holiday_status_id.unpaid', '=', True), ('time_type', '=', 'leave')])['days']
            prorata = worked / (left + worked) if worked else 0

            days_to_give = holiday.number_per_interval
            if holiday.unit_per_interval == 'hours':
                # As we encode everything in days in the database we need to convert
                # the number of hours into days for this we use the
                # mean number of hours set on the employee's calendar
                days_to_give = days_to_give / holiday.employee_id.resource_calendar_id.hours_per_day or HOURS_PER_DAY

            values['number_of_days_temp'] = holiday.number_of_days_temp + days_to_give * prorata

            if holiday.accrual_limit > 0:
                values['number_of_days_temp'] = min(values['number_of_days_temp'], holiday.accrual_limit)

            values['number_of_hours'] = values['number_of_days_temp'] * holiday.employee_id.resource_calendar_id.hours_per_day or HOURS_PER_DAY

            holiday.write(values)

    @api.multi
    @api.depends('number_of_days_temp', 'type_request_unit', 'number_of_hours', 'holiday_status_id', 'employee_id')
    def _compute_number_of_days(self):
        for holiday in self:
            number_of_days = holiday.number_of_days_temp
            if holiday.type_request_unit == 'hour':
                # In this case we need the number of days to reflect the number of hours taken
                number_of_days = holiday.number_of_hours / holiday.employee_id.resource_calendar_id.hours_per_day or HOURS_PER_DAY
            if holiday.accrual_limit > 0:
                number_of_days = min(number_of_days, holiday.accrual_limit)

            holiday.number_of_days = number_of_days

    @api.multi
    @api.depends('state', 'employee_id', 'department_id')
    def _compute_can_reset(self):
        for allocation in self:
            try:
                allocation._check_approval_update('draft')
            except (AccessError, UserError):
                allocation.can_reset = False
            else:
                allocation.can_reset = True

    @api.depends('state', 'employee_id', 'department_id')
    def _compute_can_approve(self):
        for allocation in self:
            try:
                if allocation.state == 'confirm' and allocation.holiday_status_id.validation_type == 'both':
                    allocation._check_approval_update('validate1')
                else:
                    allocation._check_approval_update('validate')
            except (AccessError, UserError):
                allocation.can_approve = False
            else:
                allocation.can_approve = True

    @api.onchange('holiday_type')
    def _onchange_type(self):
        if self.holiday_type == 'employee' and not self.employee_id:
            if self.env.user.employee_ids:
                self.employee_id = self.env.user.employee_ids[0]
        elif self.holiday_type == 'department':
            if self.env.user.employee_ids:
                self.department_id = self.department_id or self.env.user.employee_ids[0].department_id
            self.employee_id = None
        elif self.holiday_type == 'category':
            self.employee_id = None
            self.department_id = None

    @api.onchange('employee_id')
    def _onchange_employee(self):
        if self.holiday_type == 'employee':
            self.department_id = self.employee_id.department_id

    @api.onchange('number_of_days_temp')
    def _onchange_number_of_days_temp(self):
        self.number_of_hours = self.number_of_days_temp * self.employee_id.resource_calendar_id.hours_per_day

    @api.onchange('number_of_hours')
    def _onchange_number_of_hours(self):
        self.number_of_days_temp = self.number_of_hours / self.employee_id.resource_calendar_id.hours_per_day

    @api.onchange('holiday_status_id')
    def _onchange_holiday_status_id(self):
        self.date_to = datetime.combine(self.holiday_status_id.validity_stop, time.max)

        if self.accrual:
            self.number_of_days_temp = 0

            if self.holiday_status_id.request_unit == 'hour':
                self.unit_per_interval = 'hours'
            else:
                self.unit_per_interval = 'days'
        else:
            self.interval_number = 1
            self.interval_unit = 'weeks'
            self.number_per_interval = 1
            self.unit_per_interval = 'hours'

    ####################################################
    # ORM Overrides methods
    ####################################################

    @api.multi
    def name_get(self):
        res = []
        for leave in self:
            if leave.type_request_unit == 'hour':
                res.append((leave.id, _("Allocation of %s : %.2f hour(s) To %s") % (leave.holiday_status_id.name, leave.number_of_hours, leave.employee_id.name)))
            else:
                res.append((leave.id, _("Allocation of %s : %.2f day(s) To %s") % (leave.holiday_status_id.name, leave.number_of_days_temp, leave.employee_id.name)))
        return res

    @api.multi
    def add_follower(self, employee_id):
        employee = self.env['hr.employee'].browse(employee_id)
        if employee.user_id:
            self.message_subscribe(partner_ids=employee.user_id.partner_id.ids)

    @api.multi
    @api.constrains('holiday_status_id')
    def _check_leave_type_validity(self):
        for allocation in self:
            if allocation.holiday_status_id.validity_start and allocation.holiday_status_id.validity_stop:
                vstart = allocation.holiday_status_id.validity_start
                vstop = allocation.holiday_status_id.validity_stop
                today = fields.Date.today()

                if vstart > today or vstop < today:
                    raise UserError(_('You can allocate %s only between %s and %s') % (allocation.holiday_status_id.display_name,
                                                                                  allocation.holiday_status_id.validity_start, allocation.holiday_status_id.validity_stop))

    @api.model
    def create(self, values):
        """ Override to avoid automatic logging of creation """
        if values.get('accrual', False):
            values['date_from'] = fields.Datetime.now()
        employee_id = values.get('employee_id', False)
        if not values.get('department_id'):
            values.update({'department_id': self.env['hr.employee'].browse(employee_id).department_id.id})
        holiday = super(HolidaysAllocation, self.with_context(mail_create_nolog=True, mail_create_nosubscribe=True)).create(values)
        holiday.add_follower(employee_id)
        holiday.activity_update()
        return holiday

    @api.multi
    def write(self, values):
        employee_id = values.get('employee_id', False)
        if values.get('state'):
            self._check_approval_update(values['state'])
        result = super(HolidaysAllocation, self).write(values)
        self.add_follower(employee_id)
        return result

    @api.multi
    def unlink(self):
        for holiday in self.filtered(lambda holiday: holiday.state not in ['draft', 'cancel', 'confirm']):
            raise UserError(_('You cannot delete a leave which is in %s state.') % (holiday.state,))
        return super(HolidaysAllocation, self).unlink()

    @api.multi
    def copy_data(self, default=None):
        raise UserError(_('A leave cannot be duplicated.'))

    ####################################################
    # Business methods
    ####################################################

    @api.multi
    def _prepare_holiday_values(self, employee):
        self.ensure_one()
        values = {
            'name': self.name,
            'holiday_type': 'employee',
            'holiday_status_id': self.holiday_status_id.id,
            'notes': self.notes,
            'number_of_days_temp': self.number_of_days_temp,
            'parent_id': self.id,
            'employee_id': employee.id
        }
        return values

    @api.multi
    def action_draft(self):
        for holiday in self:
            if holiday.state not in ['confirm', 'refuse']:
                raise UserError(_('Leave request state must be "Refused" or "To Approve" in order to reset to Draft.'))
            holiday.write({
                'state': 'draft',
                'first_approver_id': False,
                'second_approver_id': False,
            })
            linked_requests = holiday.mapped('linked_request_ids')
            for linked_request in linked_requests:
                linked_request.action_draft()
            linked_requests.unlink()
        self.activity_update()
        return True

    @api.multi
    def action_confirm(self):
        if self.filtered(lambda holiday: holiday.state != 'draft'):
            raise UserError(_('Leave request must be in Draft state ("To Submit") in order to confirm it.'))
        res = self.write({'state': 'confirm'})
        self.activity_update()
        return res

    @api.multi
    def action_approve(self):
        # if validation_type == 'both': this method is the first approval approval
        # if validation_type != 'both': this method calls action_validate() below
        if any(holiday.state != 'confirm' for holiday in self):
            raise UserError(_('Leave request must be confirmed ("To Approve") in order to approve it.'))

        current_employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)

        self.filtered(lambda hol: hol.validation_type == 'both').write({'state': 'validate1', 'first_approver_id': current_employee.id})
        self.filtered(lambda hol: not hol.validation_type == 'both').action_validate()
        self.activity_update()
        return True

    @api.multi
    def action_validate(self):
        current_employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        for holiday in self:
            if holiday.state not in ['confirm', 'validate1']:
                raise UserError(_('Leave request must be confirmed in order to approve it.'))

            holiday.write({'state': 'validate'})
            if holiday.validation_type == 'both':
                holiday.write({'second_approver_id': current_employee.id})
            else:
                holiday.write({'first_approver_id': current_employee.id})
            if holiday.holiday_type in ['category', 'department']:
                leaves = self.env['hr.leave.allocation']
                employees = holiday.category_id.employee_ids if holiday.holiday_type == 'category' else holiday.department_id.member_ids
                for employee in employees:
                    values = holiday._prepare_holiday_values(employee)
                    leaves += self.with_context(mail_notify_force_send=False).create(values)
                # TODO is it necessary to interleave the calls?
                leaves.action_approve()
                if leaves and leaves[0].validation_type == 'both':
                    leaves.action_validate()
        self.activity_update()
        return True

    @api.multi
    def action_refuse(self):
        current_employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        for holiday in self:
            if holiday.state not in ['confirm', 'validate', 'validate1']:
                raise UserError(_('Leave request must be confirmed or validated in order to refuse it.'))

            if holiday.state == 'validate1':
                holiday.write({'state': 'refuse', 'first_approver_id': current_employee.id})
            else:
                holiday.write({'state': 'refuse', 'second_approver_id': current_employee.id})
            # If a category that created several holidays, cancel all related
            holiday.linked_request_ids.action_refuse()
        self.activity_update()
        return True

    def _check_approval_update(self, state):
        """ Check if target state is achievable. """
        current_employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        is_officer = self.env.user.has_group('hr_holidays.group_hr_holidays_user')
        is_manager = self.env.user.has_group('hr_holidays.group_hr_holidays_manager')
        for holiday in self:
            val_type = holiday.holiday_status_id.validation_type
            if state == 'confirm':
                continue

            if state == 'draft':
                if holiday.employee_id != current_employee and not is_manager:
                    raise UserError(_('Only a Leave Manager can reset other people leaves.'))
                continue

            if not is_officer:
                raise UserError(_('Only a Leave Officer or Manager can approve or refuse leave requests.'))

            if is_officer:
                # use ir.rule based first access check: department, members, ... (see security.xml)
                holiday.check_access_rule('write')

            if holiday.employee_id == current_employee and not is_manager:
                raise UserError(_('Only a Leave Manager can approve its own requests.'))

            if (state == 'validate1' and val_type == 'both') or (state == 'validate' and val_type == 'manager'):
                manager = holiday.employee_id.parent_id or holiday.employee_id.department_id.manager_id
                if (manager and manager != current_employee) and not self.env.user.has_group('hr_holidays.group_hr_holidays_manager'):
                    raise UserError(_('You must be either %s\'s manager or Leave manager to approve this leave') % (holiday.employee_id.name))

            if state == 'validate' and val_type == 'both':
                if not self.env.user.has_group('hr_holidays.group_hr_holidays_manager'):
                    raise UserError(_('Only an Leave Manager can apply the second approval on leave requests.'))

    # ------------------------------------------------------------
    # Activity methods
    # ------------------------------------------------------------

    def _get_responsible_for_approval(self):
        if self.state == 'confirm' and self.employee_id.parent_id.user_id:
            return self.employee_id.parent_id.user_id
        elif self.department_id.manager_id.user_id:
            return self.department_id.manager_id.user_id
        return self.env.user

    def activity_update(self):
        to_clean, to_do = self.env['hr.leave.allocation'], self.env['hr.leave.allocation']
        for allocation in self:
            if allocation.state == 'draft':
                to_clean |= allocation
            elif allocation.state == 'confirm':
                allocation.activity_schedule(
                    'hr_holidays.mail_act_leave_allocation_approval',
                    user_id=allocation.sudo()._get_responsible_for_approval().id)
            elif allocation.state == 'validate1':
                allocation.activity_feedback(['hr_holidays.mail_act_leave_allocation_approval'])
                allocation.activity_schedule(
                    'hr_holidays.mail_act_leave_allocation_second_approval',
                    user_id=allocation.sudo()._get_responsible_for_approval().id)
            elif allocation.state == 'validate':
                to_do |= allocation
            elif allocation.state == 'refuse':
                to_clean |= allocation
        if to_clean:
            to_clean.activity_unlink(['hr_holidays.mail_act_leave_allocation_approval', 'hr_holidays.mail_act_leave_allocation_second_approval'])
        if to_do:
            to_do.activity_feedback(['hr_holidays.mail_act_leave_allocation_approval', 'hr_holidays.mail_act_leave_allocation_second_approval'])

    ####################################################
    # Messaging methods
    ####################################################

    @api.multi
    def _track_subtype(self, init_values):
        if 'state' in init_values and self.state == 'validate':
            return 'hr_holidays.mt_leave_allocation_approved'
        elif 'state' in init_values and self.state == 'refuse':
            return 'hr_holidays.mt_leave_allocation_refused'
        return super(HolidaysAllocation, self)._track_subtype(init_values)

    @api.multi
    def _notify_get_groups(self, message, groups):
        """ Handle HR users and officers recipients that can validate or refuse holidays
        directly from email. """
        groups = super(HolidaysAllocation, self)._notify_get_groups(message, groups)

        self.ensure_one()
        hr_actions = []
        if self.state == 'confirm':
            app_action = self._notify_get_action_link('controller', controller='/allocation/validate')
            hr_actions += [{'url': app_action, 'title': _('Approve')}]
        if self.state in ['confirm', 'validate', 'validate1']:
            ref_action = self._notify_get_action_link('controller', controller='/allocation/refuse')
            hr_actions += [{'url': ref_action, 'title': _('Refuse')}]

        holiday_user_group_id = self.env.ref('hr_holidays.group_hr_holidays_user').id
        new_group = (
            'group_hr_holidays_user', lambda pdata: pdata['type'] == 'user' and holiday_user_group_id in pdata['groups'], {
                'actions': hr_actions,
            })

        return [new_group] + groups

    @api.multi
    def message_subscribe(self, partner_ids=None, channel_ids=None, subtype_ids=None):
        # due to record rule can not allow to add follower and mention on validated leave so subscribe through sudo
        if self.state in ['validate', 'validate1']:
            self.check_access_rights('read')
            self.check_access_rule('read')
            return super(HolidaysAllocation, self.sudo()).message_subscribe(partner_ids=partner_ids, channel_ids=channel_ids, subtype_ids=subtype_ids)
        return super(HolidaysAllocation, self).message_subscribe(partner_ids=partner_ids, channel_ids=channel_ids, subtype_ids=subtype_ids)

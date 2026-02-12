# Copyright (c) 2026, Richmond Gedziq and contributors
# For license information, please see license.txt

import json
import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate, today, date_diff, add_days
from typing import Optional


class RenewalTracking(Document):
    def validate(self):
        """Validate document before saving - combines all validation logic"""
        # Validate license dates
        self.validate_license_dates()
        # Set exchange rate
        self.set_exchange_rate()
        # Calculate item values
        self.calculate_item_values()
        # Calculate totals
        self.calculate_totals()
    
    def before_save(self):
        """Calculate renewal stage and other values before saving"""
        self.calculate_item_values()
        self.calculate_totals()
        # Calculate renewal stage for draft and submitted documents
        self.calculate_renewal_stage()
    
    def set_exchange_rate(self):
        """Set exchange rate from Currency Exchange doctype"""
        if not self.currency or not self.company:
            return
        
        company_currency = frappe.db.get_value('Company', self.company, 'default_currency')
        
        # For Ostec Ltd (GHS) or Ostec SA (CFA) - if base currency selected, exchange rate = 1
        if self.currency == company_currency:
            self.exchange_rate = 1.0
            return
        
        # If exchange rate already manually entered, keep it
        if self.exchange_rate and self.exchange_rate > 0:
            return
        
        # Try to find exchange rate from Currency Exchange doctype
        exchange_rate_value = frappe.db.get_value('Currency Exchange',
            {
                'from_currency': self.currency,
                'to_currency': company_currency
            },
            'exchange_rate'
        )
        
        if exchange_rate_value:
            # Found in system, store the exchange rate
            self.exchange_rate = flt(exchange_rate_value)
        else:
            # Currency pair not available in system, user must enter manually
            frappe.throw(
                f'Currency pair {self.currency} to {company_currency} not available in system. '
                'Please enter the exchange rate manually.'
            )
    
    def calculate_item_values(self):
        """Calculate amounts and base currency values for all items"""
        if not self.items:
            return
        
        # Get exchange rate
        exchange_rate = flt(self.exchange_rate) or 1.0
        company_currency = self.get_company_currency()
        
        for item in self.items:
            # Calculate amount = qty * rate
            item.amount = flt(item.qty, 2) * flt(item.rate, 2)
            
            # Calculate base currency values using exchange rate
            if self.currency and company_currency and self.currency != company_currency:
                # Different currencies - apply exchange rate
                item.base_rate = flt(item.rate, 2) * exchange_rate
                item.base_amount = flt(item.amount, 2) * exchange_rate
            else:
                # Same currency (base currency) - no conversion needed
                item.base_rate = item.rate
                item.base_amount = item.amount
    
    def calculate_totals(self):
        """Calculate net_total and net_total_base from all item lines"""
        if not self.items:
            self.net_total = 0.0
            self.net_total_base = 0.0
            return
        
        # Sum all amounts
        self.net_total = sum(flt(item.amount, 2) for item in self.items)
        
        # Sum all base amounts
        self.net_total_base = sum(flt(item.base_amount, 2) for item in self.items)
    
    def get_company_currency(self):
        """Get company's default currency"""
        if self.company:
            return frappe.db.get_value('Company', self.company, 'default_currency')
        return None
    
    def on_submit(self):
        """Calculate and update renewal stage on submission"""
        try:
            self.calculate_renewal_stage()
            frappe.db.set_value(
                'Renewal Tracking',
                self.name,
                {
                    'renewal_stage': self.renewal_stage,
                    'days_remaining': self.days_remaining
                },
                update_modified=False
            )
            frappe.db.commit()
            
            frappe.logger().info(
                f"Renewal stage set to '{self.renewal_stage}' on submission of {self.name}"
            )
        except Exception as e:
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Error calculating renewal stage on submit - {self.name}"
            )
    
    def validate_license_dates(self):
        """Validate that license dates are logical"""
        if not self.license_start or not self.license_end:
            frappe.throw("License Start and License End dates are mandatory")
        
        license_start = getdate(self.license_start)
        license_end = getdate(self.license_end)
        
        if license_end <= license_start:
            frappe.throw(
                f"License End Date ({license_end}) must be after License Start Date ({license_start})"
            )
    
    def calculate_renewal_stage(self):
        """
        Calculate and set renewal stage based on current date vs license dates
        
        Logic:
        1. nowdate < license_start → Open
        2. nowdate >= license_start AND nowdate < (license_end - 90 days) → Running
        3. nowdate >= (license_end - 90 days) AND nowdate < (license_end - 60 days) → 90 Days to Expiry
        4. nowdate >= (license_end - 60 days) AND nowdate < (license_end - 30 days) → 60 Days to Expiry
        5. nowdate >= (license_end - 30 days) AND nowdate < license_end → 30 Days to Expiry
        6. nowdate >= license_end → Expired
        
        Note: The elif chain creates implicit bounded ranges by checking from most recent to least recent
        """
        try:
            if not self.license_start or not self.license_end:
                self.renewal_stage = None
                self.days_remaining = None
                return
            
            # Get dates
            now_date = getdate(today())
            license_start = getdate(self.license_start)
            license_end = getdate(self.license_end)
            
            # Calculate days remaining until license end
            days_to_end = date_diff(license_end, now_date)
            self.days_remaining = days_to_end
            
            # Calculate milestone dates
            date_90_days_before = add_days(license_end, -90)
            date_60_days_before = add_days(license_end, -60)
            date_30_days_before = add_days(license_end, -30)
            
            # Determine renewal stage based on logic
            # Check in order from most specific to least specific
            if now_date < license_start:
                self.renewal_stage = "Open"
            elif now_date >= license_end:
                self.renewal_stage = "Expired"
            elif now_date >= date_30_days_before:
                self.renewal_stage = "30 Days to Expiry"
            elif now_date >= date_60_days_before:
                self.renewal_stage = "60 Days to Expiry"
            elif now_date >= date_90_days_before:
                self.renewal_stage = "90 Days to Expiry"
            else:
                self.renewal_stage = "Running"
            
            frappe.logger().debug(
                f"Renewal Stage calculated for {self.name}: {self.renewal_stage} "
                f"(Days remaining: {self.days_remaining})"
            )
            
        except Exception as e:
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Error calculating renewal stage for {self.name}"
            )
            self.renewal_stage = None
            self.days_remaining = None
            raise


# =============================================================================
# WHITELISTED API METHODS
# =============================================================================

#@frappe.whitelist()
#def get_items_from_sales_order(sales_order):
#    """Fetch items from Sales Order"""
#    if not sales_order:
#        return []
    
#    so_doc = frappe.get_doc('Sales Order', sales_order)
#    items = []
    
#    for item in so_doc.items:
#        items.append({
#            'item_code': item.item_code,
#            'item_name': item.item_name,
#            'description': item.description,
#            'brand': item.brand,
#            'item_group': item.item_group,
#            'oum': item.uom,
#            'qty': item.qty,
#           'rate': item.rate,
#        })
    
#    return items
@frappe.whitelist()
def get_items_from_sales_order(sales_order):
    if not sales_order:
        return []
    
    # Check for customizations
    custom_fields = frappe.get_all('Custom Field', 
        filters={'dt': 'Sales Order Item'},
        fields=['fieldname', 'label'])
    
    so_doc = frappe.get_doc('Sales Order', sales_order)
    items = []
    
    # Get ALL currency-related fields from Sales Order as they are
    currency_info = {
        'currency': so_doc.currency,  # Transaction currency
        'conversion_rate': so_doc.conversion_rate if hasattr(so_doc, 'conversion_rate') else 1.0,
        #'price_list_currency': so_doc.get('price_list_currency'),  # May be None
        #'plc_conversion_rate': so_doc.get('plc_conversion_rate'),
        #'ignore_pricing_rule': so_doc.get('ignore_pricing_rule', 0),
        'company': so_doc.company,
        'company_currency': frappe.get_cached_value('Company', so_doc.company, 'default_currency'),
    }
    
    for item in so_doc.items:
        item_dict = {
            'item_code': item.item_code,
            'item_name': item.item_name,
            'description': item.description,
            'brand': item.brand,
            'item_group': item.item_group,
            'uom': item.uom,
            'qty': item.qty,
            'rate': item.rate,
        }
        
        # Add ALL currency info from parent SO to each item
        item_dict.update(currency_info)
        
        # Add custom fields if they exist
        for field in custom_fields:
            fieldname = field['fieldname']
            if hasattr(item, fieldname):
                item_dict[fieldname] = getattr(item, fieldname)
        
        items.append(item_dict)
    
    return items

@frappe.whitelist()
def import_items(file_url, parent_doc):
    """Import items from uploaded CSV/Excel file"""
    import csv
    import openpyxl
    from frappe.utils.file_manager import get_file_path
    
    # Get the file path
    file_path = get_file_path(file_url)
    
    items = []
    
    try:
        # Determine file type and read accordingly
        if file_url.endswith('.csv'):
            # Read CSV file
            with open(file_path, 'r', encoding='utf-8-sig') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row.get('Item Code'):  # Skip empty rows
                        items.append({
                            'item_code': row.get('Item Code', ''),
                            'item_name': row.get('Item Name', ''),
                            'description': row.get('Description', ''),
                            'brand': row.get('Brand', ''),
                            'item_group': row.get('Item Group', ''),
                            'oum': row.get('UOM', ''),
                            'qty': flt(row.get('Qty', 0)),
                            'rate': flt(row.get('Rate', 0)),
                        })
        else:
            # Read Excel file
            workbook = openpyxl.load_workbook(file_path)
            sheet = workbook.active
            
            # Get headers from first row
            headers = [cell.value for cell in sheet[1]]
            
            # Read data rows
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if row[0]:  # Skip empty rows (check if Item Code exists)
                    item_data = dict(zip(headers, row))
                    items.append({
                        'item_code': item_data.get('Item Code', ''),
                        'item_name': item_data.get('Item Name', ''),
                        'description': item_data.get('Description', ''),
                        'brand': item_data.get('Brand', ''),
                        'item_group': item_data.get('Item Group', ''),
                        'oum': item_data.get('UOM', ''),
                        'qty': flt(item_data.get('Qty', 0)),
                        'rate': flt(item_data.get('Rate', 0)),
                    })
    except Exception as e:
        frappe.throw(f'Error reading file: {str(e)}')
    
    return items


@frappe.whitelist()
def make_request_for_quotation(source_name, target_doc=None):
    """Create Request for Quotation from Renewal Tracking"""
    from frappe.model.mapper import get_mapped_doc
    
    def set_missing_values(source, target):
        target.transaction_date = frappe.utils.nowdate()
        target.status = "Draft"
        target.custom_renewal_tracking = source_name
    
    def update_item(source, target, source_parent):
        target.schedule_date = frappe.utils.add_days(frappe.utils.nowdate(), 7)
    
    doclist = get_mapped_doc("Renewal Tracking", source_name, {
        "Renewal Tracking": {
            "doctype": "Request for Quotation",
            "field_map": {
                "name": "custom_renewal_tracking",
                "company": "company"
            }
        },
        "Renewal Tracking Item": {
            "doctype": "Request for Quotation Item",
            "field_map": {
                "item_code": "item_code",
                "item_name": "item_name",
                "description": "description",
                "qty": "qty",
                "oum": "uom",
                "brand": "brand"
            },
            "postprocess": update_item
        }
    }, target_doc, set_missing_values)
    
    return doclist


@frappe.whitelist()
def make_supplier_quotation(source_name, target_doc=None):
    """Create Supplier Quotation from Renewal Tracking"""
    from frappe.model.mapper import get_mapped_doc
    
    def set_missing_values(source, target):
        target.transaction_date = frappe.utils.nowdate()
        target.custom_renewal_tracking = source_name
    
    doclist = get_mapped_doc("Renewal Tracking", source_name, {
        "Renewal Tracking": {
            "doctype": "Supplier Quotation",
            "field_map": {
                "name": "custom_renewal_tracking",
                "company": "company",
                "currency": "currency",
                "exchange_rate": "conversion_rate"
            }
        },
        "Renewal Tracking Item": {
            "doctype": "Supplier Quotation Item",
            "field_map": {
                "item_code": "item_code",
                "item_name": "item_name",
                "description": "description",
                "qty": "qty",
                "oum": "uom",
                "rate": "rate",
                "amount": "amount",
                "brand": "brand"
            }
        }
    }, target_doc, set_missing_values)
    
    return doclist


@frappe.whitelist()
def make_quotation(source_name, target_doc=None):
    """Create Customer Quotation from Renewal Tracking"""
    from frappe.model.mapper import get_mapped_doc
    
    def set_missing_values(source, target):
        target.transaction_date = frappe.utils.nowdate()
        target.valid_till = frappe.utils.add_days(frappe.utils.nowdate(), 30)
        target.custom_renewal_tracking = source_name
    
    doclist = get_mapped_doc("Renewal Tracking", source_name, {
        "Renewal Tracking": {
            "doctype": "Quotation",
            "field_map": {
                "name": "custom_renewal_tracking",
                "company": "company",
                "currency": "currency",
                "exchange_rate": "conversion_rate"
            }
        },
        "Renewal Tracking Item": {
            "doctype": "Quotation Item",
            "field_map": {
                "item_code": "item_code",
                "item_name": "item_name",
                "description": "description",
                "qty": "qty",
                "oum": "uom",
                "rate": "rate",
                "amount": "amount",
                "brand": "brand"
            }
        }
    }, target_doc, set_missing_values)
    
    return doclist


@frappe.whitelist()
def update_single_renewal_stage(docname: str) -> dict:
    """
    Manually update renewal stage for a specific document
    
    Args:
        docname: Name of the Renewal Tracking document
    
    Returns:
        dict with updated renewal_stage and days_remaining
    """
    try:
        if not frappe.has_permission('Renewal Tracking', 'write', docname):
            frappe.throw("Insufficient permissions to update this document")
        
        doc = frappe.get_doc('Renewal Tracking', docname)
        old_stage = doc.renewal_stage
        
        doc.calculate_renewal_stage()
        
        # Update directly in database to avoid triggering workflows
        frappe.db.set_value(
            'Renewal Tracking',
            docname,
            {
                'renewal_stage': doc.renewal_stage,
                'days_remaining': doc.days_remaining
            },
            update_modified=False
        )
        frappe.db.commit()
        
        return {
            'success': True,
            'renewal_stage': doc.renewal_stage,
            'days_remaining': doc.days_remaining,
            'message': f'Renewal stage updated from "{old_stage}" to "{doc.renewal_stage}"'
        }
        
    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"Error updating renewal stage for {docname}"
        )
        return {
            'success': False,
            'error': str(e)
        }


# =============================================================================
# SCHEDULED TASKS
# =============================================================================

def update_all_renewal_stages_heavy():
    """
    Heavy job: Update ALL renewal tracking records (runs at 2 AM daily)
    Processes all submitted (docstatus=1) documents with valid license dates
    """
    try:
        frappe.logger().info("Starting HEAVY renewal stage update job at 2 AM")
        
        # Get all SUBMITTED renewal tracking documents
        filters = {
            'docstatus': 1,  # Only submitted documents
            'license_start': ['is', 'set'],
            'license_end': ['is', 'set']
        }
        
        renewal_docs = frappe.get_all(
            'Renewal Tracking',
            filters=filters,
            pluck='name'
        )
        
        total_count = len(renewal_docs)
        success_count = 0
        error_count = 0
        errors = []
        stage_changes = []
        
        frappe.logger().info(f"Found {total_count} submitted renewal tracking records to process")
        
        for idx, name in enumerate(renewal_docs, 1):
            try:
                doc = frappe.get_doc('Renewal Tracking', name)
                old_stage = doc.renewal_stage
                
                # Calculate new stage
                doc.calculate_renewal_stage()
                
                # Update database directly without affecting docstatus
                frappe.db.set_value(
                    'Renewal Tracking',
                    name,
                    {
                        'renewal_stage': doc.renewal_stage,
                        'days_remaining': doc.days_remaining
                    },
                    update_modified=False  # Don't update modified timestamp
                )
                
                # Track stage changes
                if old_stage != doc.renewal_stage:
                    stage_changes.append({
                        'name': name,
                        'old_stage': old_stage,
                        'new_stage': doc.renewal_stage,
                        'days_remaining': doc.days_remaining
                    })
                    frappe.logger().info(
                        f"[{idx}/{total_count}] {name}: {old_stage} → {doc.renewal_stage}"
                    )
                
                success_count += 1
                
                # Commit every 50 records to prevent long transactions
                if idx % 50 == 0:
                    frappe.db.commit()
                    frappe.logger().info(f"Progress: {idx}/{total_count} records processed")
                
            except Exception as e:
                error_count += 1
                error_msg = f"Error updating {name}: {str(e)}"
                errors.append(error_msg)
                frappe.log_error(
                    message=frappe.get_traceback(),
                    title=f"Heavy Job Error - {name}"
                )
                continue
        
        # Final commit
        frappe.db.commit()
        
        # Summary logging
        summary = (
            f"HEAVY Job Completed:\n"
            f"Total: {total_count}\n"
            f"Success: {success_count}\n"
            f"Errors: {error_count}\n"
            f"Stage Changes: {len(stage_changes)}"
        )
        
        frappe.logger().info(summary)
        
        if stage_changes:
            change_details = "\n".join([
                f"{c['name']}: {c['old_stage']} → {c['new_stage']} ({c['days_remaining']} days)"
                for c in stage_changes
            ])
            frappe.logger().info(f"Stage Changes:\n{change_details}")
        
        if errors:
            frappe.log_error(
                message="\n".join(errors),
                title="Heavy Job - Failed Updates Summary"
            )
        
        return {
            'total': total_count,
            'success': success_count,
            'errors': error_count,
            'stage_changes': len(stage_changes)
        }
        
    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(),
            title="Heavy Renewal Stage Update Job Failed"
        )
        raise
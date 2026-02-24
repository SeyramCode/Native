// Copyright (c) 2026, Richmond Gedziq and contributors
// For license information, please see license.txt

frappe.ui.form.on('Renewal Tracking', {
    refresh: function(frm) {
        // Recalculate items on refresh to ensure values are correct
        if (frm.doc.items && frm.doc.items.length > 0) {
            frm.doc.items.forEach(function(item) {
                calculate_item_values(frm, item.doctype, item.name);
            });
        }
        // Make details,contacts and connection tab visible
        if (frm.docstatus === 1) {
            ['details_tab','contacts_tab','connections_tab'].forEach(function(tab)
            {let field = frm.fields_dict[tab];
                if (field) {
                    field.df.hidden = 0;
                    frm.refresh_field(tab);
                }
            });
        }
        // Add Upload/Download buttons for items table with delay to ensure grid is rendered
        setTimeout(function() {
            add_upload_download_buttons(frm);
        }, 500);
        
        // Add "Fetch from Sales Order" button if document is in draft and customer_po is selected
        if (frm.doc.docstatus === 0 && frm.doc.customer_po) {
            frm.add_custom_button(__('Fetch from Sales Order'), function() {
                fetch_items_from_sales_order(frm);
            }, __('Get Items'));
        }
        
        // Add custom buttons to create documents
        if (frm.doc.docstatus === 1) {
            // Request for Quotation button
            frm.add_custom_button(__('Request for Quotation'), function() {
                frappe.model.open_mapped_doc({
                    method: "native.native.doctype.renewal_tracking.renewal_tracking.make_request_for_quotation",
                    frm: frm
                });
            }, __('Create'));
            
            // Supplier Quotation button
            frm.add_custom_button(__('Supplier Quotation'), function() {
                frappe.model.open_mapped_doc({
                    method: "native.native.doctype.renewal_tracking.renewal_tracking.make_supplier_quotation",
                    frm: frm
                });
            }, __('Create'));
            
            // Customer Quotation button
            frm.add_custom_button(__('Quotation'), function() {
                frappe.model.open_mapped_doc({
                    method: "native.native.doctype.renewal_tracking.renewal_tracking.make_quotation",
                    frm: frm
                });
            }, __('Create'));
        }
    },
    
    company: function(frm) {
        // When company changes, reset and recalculate
        if (frm.doc.currency) {
            get_exchange_rate(frm);
        }
    },
    
    customer: function(frm) {
        // When customer changes, clear Sales Order and items
        if (frm.doc.customer_po || (frm.doc.items && frm.doc.items.length > 0)) {
            frappe.confirm(
                __('Changing the Customer will clear the Sales Order and all items. Do you want to continue?'),
                function() {
                    // User confirmed - clear Sales Order and items
                    frm.set_value('customer_po', '');
                    frm.clear_table('items');
                    frm.refresh_field('items');
                    calculate_totals(frm);
                },
                function() {
                    // User cancelled - revert the customer change
                    frm.set_value('customer', frm.doc.__last_customer || '');
                }
            );
        }
        
        // Store the current value for potential revert
        frm.doc.__last_customer = frm.doc.customer;
    },
    customer_po: function(frm) {
        if (frm.doc.items && frm.doc.items.length > 0) {
            frappe.confirm(
                __('Changing the Sales Order will clear all items. Do you want to continue?'),
                function() {
                    // User confirmed - clear items
                    frm.clear_table('items');
                    frm.refresh_field('items');
                    calculate_totals(frm);
                    // Refresh to show/hide fetch button
                    frm.refresh();
                },
                function() {
                    // User cancelled - revert the Sales Order change
                    frm.set_value('customer_po', frm.doc.__last_customer_po || '');
                }
            );
        } else {
            // No items, just refresh
            frm.refresh();
        }
        
        // Store the current value for potential revert
        frm.doc.__last_customer_po = frm.doc.customer_po;
    },

    currency: function(frm) {
        // Fetch exchange rate when currency changes (only if not from Sales Order)
        if (!frm.__fetching_from_sales_order) {
            get_exchange_rate(frm);
        }
    },
    
    exchange_rate: function(frm) {
        // Recalculate all items when exchange rate changes
        if (frm.doc.items && frm.doc.items.length > 0) {
            frm.doc.items.forEach(function(item) {
                calculate_item_values(frm, item.doctype, item.name);
            });
        }
        calculate_totals(frm);
    },
    
    license_start: function(frm) {
        validate_and_calculate(frm);
    },
    
    license_end: function(frm) {
        validate_and_calculate(frm);
    }
});

frappe.ui.form.on('Renewal Tracking Item', {
    qty: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn);
        calculate_totals(frm);
    },
    
    rate: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn);
        calculate_totals(frm);
    },
    
    items_add: function(frm, cdt, cdn) {
        calculate_item_values(frm, cdt, cdn);
        calculate_totals(frm);
        // Re-add buttons after adding new row
        setTimeout(function() {
            add_upload_download_buttons(frm);
        }, 300);
    },
    
    items_remove: function(frm) {
        calculate_totals(frm);
    }
});

function add_upload_download_buttons(frm) {
    // Get the items grid
    let grid = frm.fields_dict.items.grid;
    
    if (!grid || !grid.wrapper) return;
    
    // Find or create the grid buttons area
    let grid_buttons_area = grid.wrapper.find('.grid-buttons');
    
    if (!grid_buttons_area.length) {
        // If grid-buttons doesn't exist, create it
        let grid_footer = grid.wrapper.find('.grid-footer');
        if (grid_footer.length) {
            grid_footer.prepend('<div class="grid-buttons"></div>');
            grid_buttons_area = grid.wrapper.find('.grid-buttons');
        } else {
            return;
        }
    }
    
    // Remove existing custom buttons to prevent duplicates
    grid_buttons_area.find('.custom-upload-download-buttons').remove();
    
    // Create button container with right alignment
    let button_html = `
        <div class="custom-upload-download-buttons" style="float: right; margin-right: 10px;">
            <button class="btn btn-xs btn-default btn-download-items" type="button" style="margin-left: 5px;">
                <svg class="icon icon-sm" style=""><use href="#icon-download"></use></svg>
                ${__('Download')}
            </button>
    `;
    
    // Add Upload button only if document is not submitted
    if (frm.doc.docstatus === 0) {
        button_html += `
            <button class="btn btn-xs btn-default btn-upload-items" type="button" style="margin-left: 5px;">
                <svg class="icon icon-sm" style=""><use href="#icon-upload"></use></svg>
                ${__('Upload')}
            </button>
        `;
    }
    
    button_html += '</div>';
    
    grid_buttons_area.prepend(button_html);
    
    // Attach click handlers
    grid_buttons_area.find('.btn-download-items').off('click').on('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        download_items_template(frm);
        return false;
    });
    
    grid_buttons_area.find('.btn-upload-items').off('click').on('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        upload_items_from_file(frm);
        return false;
    });
    
    // Prevent Enter key from triggering download
    grid_buttons_area.find('.btn-download-items, .btn-upload-items').on('keydown', function(e) {
        if (e.keyCode === 13) { // Enter key
            e.preventDefault();
            e.stopPropagation();
            $(this).click();
            return false;
        }
    });
}

function download_items_template(frm) {
    // Prepare data for download
    let data = [];
    
    // Add headers
    data.push([
        'Item Code',
        'Item Name',
        'Description',
        'Brand',
        'Item Group',
        'UOM',
        'Qty',
        'Rate',
        'Amount',
        'Base Rate',
        'Base Amount'
    ]);
    
    // Add existing items data
    if (frm.doc.items && frm.doc.items.length > 0) {
        frm.doc.items.forEach(function(item) {
            data.push([
                item.item_code || '',
                item.item_name || '',
                item.description ? strip_html(item.description) : '',
                item.brand || '',
                item.item_group || '',
                item.oum || '',
                item.qty || 0,
                item.rate || 0,
                item.amount || 0,
                item.base_rate || 0,
                item.base_amount || 0
            ]);
        });
    } else {
        // Add empty rows as template
        for (let i = 0; i < 5; i++) {
            data.push(['', '', '', '', '', '', '', '', '', '', '']);
        }
    }
    
    // Create CSV content
    let csv_content = data.map(row => row.map(cell => {
        // Escape double quotes and wrap in quotes if contains comma
        let cell_str = String(cell);
        if (cell_str.includes(',') || cell_str.includes('"') || cell_str.includes('\n')) {
            return '"' + cell_str.replace(/"/g, '""') + '"';
        }
        return cell_str;
    }).join(',')).join('\n');
    
    // Download file
    let blob = new Blob([csv_content], { type: 'text/csv;charset=utf-8;' });
    let link = document.createElement('a');
    let url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', 'renewal_tracking_items_' + (frm.doc.name || 'template') + '.csv');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    frappe.show_alert({
        message: __('Items downloaded successfully'),
        indicator: 'green'
    });
}

function upload_items_from_file(frm) {
    // Check if document is submitted
    if (frm.doc.docstatus === 1) {
        frappe.msgprint(__('Cannot upload items to a submitted document'));
        return;
    }
    
    // Create file upload dialog
    new frappe.ui.FileUploader({
        doctype: frm.doctype,
        docname: frm.docname,
        frm: frm,
        folder: 'Home',
        restrictions: {
            allowed_file_types: ['.csv', '.xlsx', '.xls']
        },
        on_success: function(file_doc) {
            // Process the uploaded file
            frappe.call({
                method: 'native.native.doctype.renewal_tracking.renewal_tracking.import_items',
                args: {
                    file_url: file_doc.file_url,
                    parent_doc: frm.doc.name
                },
                callback: function(r) {
                    if (r.message) {
                        // Clear existing items
                        frm.clear_table('items');
                        
                        // Add imported items
                        r.message.forEach(function(item_data) {
                            let item = frm.add_child('items');
                            Object.assign(item, item_data);
                        });
                        
                        // Refresh and recalculate
                        frm.refresh_field('items');
                        
                        // Recalculate all values
                        frm.doc.items.forEach(function(item) {
                            calculate_item_values(frm, item.doctype, item.name);
                        });
                        calculate_totals(frm);
                        
                        frappe.show_alert({
                            message: __('Items imported successfully'),
                            indicator: 'green'
                        });
                    }
                }
            });
        }
    });
}

function strip_html(html) {
    if (!html) return '';
    let tmp = document.createElement('DIV');
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || '';
}

function get_exchange_rate(frm) {
    if (!frm.doc.currency || !frm.doc.company) {
        return;
    }
    
    // Get company currency
    frappe.db.get_value('Company', frm.doc.company, 'default_currency', function(r) {
        let company_currency = r.default_currency;
        
        // Check if base currency is selected
        if (frm.doc.currency === company_currency) {
            // Base currency selected, exchange rate = 1
            frm.set_value('exchange_rate', 1.0);
            return;
        }
        
        // Try to find LATEST exchange rate from Currency Exchange doctype
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Currency Exchange',
                filters: {
                    from_currency: frm.doc.currency,
                    to_currency: company_currency
                },
                fields: ['exchange_rate', 'date'],
                order_by: 'date desc',
                limit_page_length: 1
            },
            callback: function(response) {
                if (response.message && response.message.length > 0) {
                    // Found exchange rate in system, set the latest one
                    let latest_rate = response.message[0].exchange_rate;
                    frm.set_value('exchange_rate', flt(latest_rate));
                } else {
                    // Currency pair not available, clear field and show message
                    frm.set_value('exchange_rate', 0.0);
                    frappe.msgprint({
                        title: __('Exchange Rate Not Found'),
                        indicator: 'orange',
                        message: __(`Currency pair ${frm.doc.currency} to ${company_currency} not found in system. Please enter the exchange rate manually in the Exchange Rate field.`)
                    });
                }
            }
        });
    });
}

function calculate_item_values(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    
    if (!row) return;
    
    // Calculate amount = qty * rate
    row.amount = flt(row.qty, 2) * flt(row.rate, 2);
    
    // Get exchange rate from parent document
    let exchange_rate = flt(frm.doc.exchange_rate) || 1.0;
    
    // Get company currency to check if conversion is needed
    if (!frm.doc.company) {
        row.base_rate = row.rate;
        row.base_amount = row.amount;
        frm.refresh_field('items');
        return;
    }
    
    frappe.db.get_value('Company', frm.doc.company, 'default_currency', function(r) {
        let company_currency = r.default_currency;
        
        // Check if currency conversion is needed
        if (frm.doc.currency && company_currency && frm.doc.currency !== company_currency) {
            // Different currencies - apply exchange rate
            row.base_rate = flt(row.rate, 2) * exchange_rate;
            row.base_amount = flt(row.amount, 2) * exchange_rate;
        } else {
            // Same currency (base currency) - no conversion needed
            row.base_rate = row.rate;
            row.base_amount = row.amount;
        }
        
        // Refresh the child table field
        frm.refresh_field('items');
    });
}

function calculate_totals(frm) {
    if (!frm.doc.items || frm.doc.items.length === 0) {
        frm.set_value('net_total', 0.0);
        frm.set_value('net_total_base', 0.0);
        return;
    }
    
    let net_total = 0.0;
    let net_total_base = 0.0;
    
    // Sum all amounts and base amounts
    frm.doc.items.forEach(function(item) {
        net_total += flt(item.amount, 2);
        net_total_base += flt(item.base_amount, 2);
    });
    
    frm.set_value('net_total', net_total);
    frm.set_value('net_total_base', net_total_base);
}

function validate_and_calculate(frm) {
    if (!frm.doc.license_start || !frm.doc.license_end) {
        return;
    }
    
    // Validate dates
    let license_start = frappe.datetime.str_to_obj(frm.doc.license_start);
    let license_end = frappe.datetime.str_to_obj(frm.doc.license_end);
    
    if (license_end <= license_start) {
        frappe.msgprint({
            title: __('Invalid Dates'),
            indicator: 'red',
            message: __('License End Date must be after License Start Date')
        });
        frm.set_value('license_end', '');
        return;
    }
    
    // Calculate days remaining
    let today = frappe.datetime.get_today();
    let days_remaining = frappe.datetime.get_day_diff(frm.doc.license_end, today);
    frm.set_value('days_remaining', Math.max(0,days_remaining)); //clamp to 0 to avoid negative values
}

function fetch_items_from_sales_order(frm) {
    if (!frm.doc.customer_po) {
        frappe.msgprint(__('Please select a Sales Order first'));
        return;
    }
    
    frappe.call({
        method: 'native.native.doctype.renewal_tracking.renewal_tracking.get_items_from_sales_order',
        args: {
            sales_order: frm.doc.customer_po
        },
        callback: function(r) {
            if (r.message && r.message.items && r.message.items.length > 0) {
                // Set flag to prevent currency event from firing
                frm.__fetching_from_sales_order = true;
                
                // Set currency and exchange rate from Sales Order
                if (r.message.currency) {
                    frm.set_value('currency', r.message.currency);
                }
                if (r.message.exchange_rate) {
                    frm.set_value('exchange_rate', r.message.exchange_rate);
                }
                
                // Clear flag after a brief delay
                setTimeout(function() {
                    frm.__fetching_from_sales_order = false;
                }, 500);
                
                // Ask user if they want to replace existing items or append
                if (frm.doc.items && frm.doc.items.length > 0) {
                    frappe.confirm(
                        __('Do you want to replace existing items or append the new items?'),
                        function() {
                            // Replace - clear existing items
                            frm.clear_table('items');
                            add_fetched_items(frm, r.message.items);
                        },
                        function() {
                            // Append - keep existing items
                            add_fetched_items(frm, r.message.items);
                        }
                    );
                } else {
                    // No existing items, just add
                    add_fetched_items(frm, r.message.items);
                }
            } else {
                frappe.msgprint(__('No items found in the selected Sales Order'));
            }
        }
    });
}

function add_fetched_items(frm, items) {
    items.forEach(function(item_data) {
        let item = frm.add_child('items');
        Object.assign(item, item_data);
    });
    
    // Refresh and recalculate
    frm.refresh_field('items');
    
    // Recalculate all values
    frm.doc.items.forEach(function(item) {
        calculate_item_values(frm, item.doctype, item.name);
    });
    calculate_totals(frm);
    
    frappe.show_alert({
        message: __('Items fetched successfully from Sales Order'),
        indicator: 'green'
    });
}
// Copyright (c) 2026, Ostec and contributors
// For license information, please see license.txt

frappe.listview_settings['Renewal Tracking'] = {
    add_fields: ["renewal_stage", "days_remaining", "license_start", "license_end"],
    
    formatters: {
        days_remaining: function(value, df, doc) {
            if (value === null || value === undefined) {
                return '';
            }
            
            let color, text;
            if (value < 0) {
                color = 'red';
                text = Math.abs(value) + ' days overdue';
            } else if (value <= 30) {
                color = 'red';
                text = value + ' days';
            } else if (value <= 60) {
                color = 'orange';
                text = value + ' days';
            } else if (value <= 90) {
                color = 'yellow';
                text = value + ' days';
            } else {
                color = 'green';
                text = value + ' days';
            }
            
            return `<span style="color: ${color}; font-weight: bold;">${text}</span>`;
        }
    }
};
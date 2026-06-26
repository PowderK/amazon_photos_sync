<?php
/**
 * Plugin Name: NINA Warnungen für unsere Region
 * Description: Zeigt aktuelle Katastrophenschutz-Warnungen aus der NINA API für unsere Region an.
 * Version: 1.8
 * Author: Dein Name
 */

if (!defined('ABSPATH')) {
    exit; // Direktzugriff verhindern
}

// API-Endpunkt für deine Region
define('NINA_API_URL', 'https://warnung.bund.de/api31/dashboard/033510000000.json');

// Übersetzungsfunktionen für severity & msgType
function nina_translate_severity($severity) {
    $translations = [
        'Extreme' => 'Lebensbedrohlich',
        'Severe' => 'Schwere Gefahr',
        'Moderate' => 'Mittlere Gefahr',
        'Minor' => 'Geringe Gefahr'
    ];
    return $translations[$severity] ?? 'Unbekannt';
}

function nina_translate_msgType($msgType) {
    $translations = [
        'Alert' => 'Neue Warnung',
        'Update' => 'Aktualisierte Warnung',
        'Cancel' => 'Warnung wurde aufgehoben'
    ];
    return $translations[$msgType] ?? 'Unbekannt';
}

// Hintergrundfarbe je nach Schweregrad
function nina_get_severity_color($severity) {
    $colors = [
        'Extreme' => '#ff0000',  // Rot
        'Severe' => '#ff6600',   // Orange-Rot
        'Moderate' => '#ffcc00', // Gelb
        'Minor' => '#66cc66'     // Grün
    ];
    return $colors[$severity] ?? '#cccccc'; // Standard-Grau bei unbekannten Werten
}

// API-Daten abrufen und anzeigen
function nina_warnungen_holen() {
    $response = wp_remote_get(NINA_API_URL);

    if (is_wp_error($response)) {
        return '<p>Fehler beim Abrufen der Daten.</p>';
    }

    $data = json_decode(wp_remote_retrieve_body($response), true);

    if (empty($data)) {
        return '<div class="nina-keine-warnungen">
                    <p class="nina-keine-warnung-text">Keine aktuellen Warnungen für Adelheidsdorf.</p>
                    <p class="nina-quellenangabe">Bundesamt für Bevölkerungsschutz und Katastrophenhilfe</p>
                </div>';
    }

    $output = '<div class="nina-warnungen">';

    foreach ($data as $warnung) {
        if (!isset($warnung['payload']['data'])) {
            continue;
        }

        $warnung_data = $warnung['payload']['data'];
        
        // Deutsche Überschrift aus "i18nTitle", falls vorhanden
        if (!empty($warnung['i18nTitle']['de'])) {
            $headline = esc_html($warnung['i18nTitle']['de']);
        } else {
            $headline = isset($warnung_data['headline']) ? esc_html($warnung_data['headline']) : 'Keine Überschrift';
        }

        $provider = isset($warnung_data['provider']) ? esc_html($warnung_data['provider']) : 'Unbekannter Anbieter';
        $severity_key = $warnung_data['severity'] ?? 'Unbekannt';
        $severity = nina_translate_severity($severity_key);
        $msgType = isset($warnung_data['msgType']) ? nina_translate_msgType($warnung_data['msgType']) : 'Unbekannt';

        $background_color = nina_get_severity_color($severity_key);

        // Link zur Warnung
        if (!empty($warnung_data['web'])) {
            $warnung_link = esc_url($warnung_data['web']);
        } else {
            $warnung_link = 'https://www.google.com/search?q=' . urlencode($headline);
        }

        // Einzelne Warnung mit Hintergrundfarbe ausgeben
        $output .= '<div class="nina-warnung-box" style="background-color:' . $background_color . ';">';
        $output .= '<div class="nina-headline"><a href="' . $warnung_link . '" target="_blank">' . $headline . '</a></div>';
        $output .= '<div class="nina-details">Schweregrad: ' . $severity . '<br>Meldungstyp: ' . $msgType . '</div>';
        $output .= '<div class="nina-provider">Quelle: ' . $provider . '</div>';
        $output .= '</div>';
    }

    $output .= '</div>';

    return $output;
}

// Shortcode für die Anzeige der Warnungen
function nina_warnungen_shortcode() {
    return nina_warnungen_holen();
}
add_shortcode('nina_warnungen', 'nina_warnungen_shortcode');

// Optional: CSS für bessere Darstellung
    function nina_warnungen_styles() {
        echo '<style>
            .nina-warnungen { max-width: 600px; margin: 20px auto; line-height: 1.6; }
            .nina-warnung-box {
                padding: 20px;
                border-radius: 5px;
                margin-bottom: 15px;
                font-size: 16px;
                color: #000;
                position: relative;
                line-height: 1.6;
            }
            .nina-headline {
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 12px;
                line-height: 1.6;
            }
            .nina-headline a {
                text-decoration: none;
                color: black;
            }
            .nina-headline a:hover {
                text-decoration: underline;
            }
            .nina-details {
                font-size: 16px;
                font-weight: normal;
                line-height: 1.6;
            }
            .nina-provider {
                font-size: 14px;
                color: #555;
                position: absolute;
                right: 10px;
                bottom: 10px;
                line-height: 1.6;
            }
            .nina-keine-warnungen {
                text-align: center;
                font-weight: bold;
                font-size: 24px;
                margin-top: 0px;
                line-height: 1.8;
            }
            .nina-quellenangabe {
                font-size: 12px;
                color: #999;
                text-align: right;
                margin-top: 8px;
                line-height: 1.6;
            }
        </style>';
    }
add_action('wp_head', 'nina_warnungen_styles');
?>

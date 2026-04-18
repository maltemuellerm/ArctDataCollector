<?php
// Placeholder conversion script.
// Adapt this to fetch decoded JSON and convert it into GeoJSON for frontend use.

$input_url = "https://openmetbuoy-arctic.com/master-decoded.json";
$output_file = __DIR__ . "/../data/decoded_fixes.geojson";

$json_data = @file_get_contents($input_url);
if ($json_data === false) {
    http_response_code(500);
    echo "Failed to fetch JSON from $input_url";
    exit;
}

$data = json_decode($json_data, true);
if (!is_array($data)) {
    http_response_code(500);
    echo "Invalid JSON structure";
    exit;
}

$geojson = [
    "type" => "FeatureCollection",
    "features" => [],
];

file_put_contents($output_file, json_encode($geojson, JSON_PRETTY_PRINT));
echo "GeoJSON updated: $output_file\n";

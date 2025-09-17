<?php

$filePath = 'patikey.txt';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $inputText = $_POST['input_text'];
    $lines = explode("\n", $inputText);
    $existingContent = file_get_contents($filePath);
    foreach ($lines as $line) {
        $trimmedLine = trim($line);
        if (!empty($trimmedLine) && strpos($existingContent, $trimmedLine) === false) {
            $existingContent .= $trimmedLine . PHP_EOL;
        }
    }
    file_put_contents($filePath, $existingContent);
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mega Death Path Keywords Adder.</title>
</head>
<body>
    <form method="post">
        <label for="input_text">Paths (one per line):</label><br>
        <textarea name="input_text" rows="5" cols="40"></textarea><br>
        <input type="submit" value="Submit">
    </form>
</body>
</html>

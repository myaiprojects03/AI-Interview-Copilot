# Builds a mock interview recording with Windows' built-in text-to-speech (free, offline).
# Output: 16 kHz mono 16-bit WAV, the interviewer asking questions with gaps for answers.
#
#   powershell -ExecutionPolicy Bypass -File backend/scripts/make_mock_interview.ps1
param(
    [string]$Out = (Join-Path $PSScriptRoot "..\..\frontend\public\demo\mock-interview.wav"),
    [int]$GapSeconds = 8
)

Add-Type -AssemblyName System.Speech

$lines = @(
    "Hi, thanks for joining today. Let's get started. Can you tell me a little about yourself?",
    "Great, thanks. Tell me about a time you had a disagreement with another team. How did you handle it?",
    "Okay. How would you design a rate limiter for a public API?",
    "Nice. What's the difference between a process and a thread?",
    "I see you worked on a payments system. What was the hardest production incident you dealt with there?",
    "And finally, why do you want to work here?"
)

$out = [System.IO.Path]::GetFullPath($Out)
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like "en-*" } | Select-Object -First 1
if ($voice) { $synth.SelectVoice($voice.VoiceInfo.Name) }
$synth.Rate = 0

$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth.SetOutputToWaveFile($out, $format)

$prompt = New-Object System.Speech.Synthesis.PromptBuilder
$prompt.AppendBreak([TimeSpan]::FromSeconds(1))
foreach ($line in $lines) {
    $prompt.AppendText($line)
    $prompt.AppendBreak([TimeSpan]::FromSeconds($GapSeconds))
}
$synth.Speak($prompt)
$synth.Dispose()

Write-Output "Wrote $out ($([math]::Round((Get-Item $out).Length / 1MB, 2)) MB)"

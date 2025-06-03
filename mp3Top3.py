public void ConvertMp3ToWav(string mp3Path, string wavPath)
int rate=16000.
int channels =1;
'=new Mp3FileReaderBase(mp3Path, wf =》new Mp3FrameDecompressor(wf))using (var reader
//转换为 SampleProvider(浮点格式)
var sampleProvider = reader.ToSampleProvider(),立体声转单声道(如果MP3是双声道)
if(reader.WaveFormat.Channels >channels)
sampleProvider = new StereoToMonoSampleProvider(sampleProvider);
//重采样到目标采样率
var resampler = new wdlResamplingSampleProvider(sampleProvider, rate)//写À WAV 文件
WaveFileWriter.CreateWaveFile16(wavPath, resampler),
Console.writeLine("MP3 转 WAV 完成!");
G公众号·WPF程序员

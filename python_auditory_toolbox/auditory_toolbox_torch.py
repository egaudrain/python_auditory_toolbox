"""A PyTorch port of portions of the Matlab Auditory Toolbox.
"""
import math
from typing import List, Optional, Tuple
import torch
from torch import nn
from torchaudio.functional import lfilter


class ErbFilterBank(nn.Module):
  """Applies an Auditory Filterbank to data of dimension of `(..., time)` as
  described in the 'Auditory Toolbox - An Efficient Implementation of the
  Patterson-Holdsworth Auditory Filter Bank' by Malcolm Slaney, available on:
  <https://engineering.purdue.edu/~malcolm/interval/1998-010/AuditoryToolboxTechReport.pdf>

  Args:
  ----------
    num_channels : int
      How many channels in the filterbank. Default: 64
    lowest_frequency : float 
      The lowest center frequency of the filterbank. Default: 100.
    sampling_rate : float
      Sampling rate (in Hz) of the filterbank (needed to determine CFs).
      Default: 16000
    dtype: (Optional) 
      Cast coefficients to dtype after instantiation. Default: None

  .. note::
      The implementation does not attempt to account for filtering delays.
      Note also that uniform temporal sampling is assumed and that the data
      are not mean-centered or zero-padded prior to filtering.

  Examples:
      >>> fbank = ErbFilterBank(sampling_rate=16000)
      >>> fbank = m.to(device=torch.device("cpu"), dtype=torch.float32)
      >>> input = torch.zeros(1,512,dtype=torch.float32)
      >>> input[0,0 ] = 1.
      >>> output = m(input)

  Attributes:
      fcoefs: Filter coefficients generated by make_erb_filters
      sos: Coefficients used for subsequent filtering.
  """
  __constants__ = ['sampling_rate', 'num_channels', 'lowest_frequency']

  def __init__(
          self,
          sampling_rate: float = 16000.,
          num_channels: int = 64,
          lowest_frequency: float = 100.,
          dtype: Optional[torch.dtype] = None,
  ) -> None:
    super().__init__()
    if sampling_rate <= 0:
      raise ValueError('Sampling rate cannoy be negative or zero')
    if lowest_frequency <= 0 or lowest_frequency >= sampling_rate/2:
      raise ValueError('Misspecified lowest frequency')

    self.sampling_rate = sampling_rate
    self.num_channels = num_channels
    self.lowest_frequency = lowest_frequency
    self.fcoefs = make_erb_filters(self.sampling_rate,
                                   self.num_channels,
                                   self.lowest_frequency)
    if dtype:
      sos = prepare_coefficients(self.fcoefs).to(dtype=dtype)
    else:
      sos = prepare_coefficients(self.fcoefs)

    self.register_buffer('sos', sos)

  def forward(self, x: torch.Tensor) -> torch.Tensor:
    """Pass audio through the set of filters.

    The code is directly adapted from: 'Auditory Toolbox - An Efficient
    Implementation of the Patterson-Holdsworth Auditory Filter Bank' by
    Malcolm Slaney.

    Parameters
    ----------
    x : torch.Tensor
      The input signal of dimension (..., time).

    Returns
    -------
    y : torch.Tensor: 
      Output signal of dimension (..., num_channels, time).
      
    """
    if x.ndim < 2:
      raise TypeError('The input tensor should have size `(..., time)`')
    if x.shape[-1] <= 1:
      raise TypeError('The input tensor should have size `(..., time)`')
    new_dims = [1 for j in list(x.unsqueeze(-2).shape)]
    new_dims[-2] = self.num_channels

    y = lfilter(x.unsqueeze(-2).tile(new_dims),
                self.sos[..., -1],
                self.sos[..., 0],
                clamp=False, batching=True)

    for j in range(3):
      y = lfilter(y,
                  self.sos[..., -1],
                  self.sos[..., j+1],
                  clamp=False, batching=True)

    return y


def erb_space(low_freq: float = 100,
              high_freq: float = 44100/4,
              n: int = 100) -> torch.Tensor:
  """Compute frequencies uniformly spaced on an erb scale.

  The code is directly adapted from: 'Auditory Toolbox - An Efficient
  Implementation of the Patterson-Holdsworth Auditory Filter Bank' by
  Malcolm Slaney.

  For a definition of erb, see Moore, B. C. J., and Glasberg, B. R. (1983).
  "Suggested formulae for calculating auditory-filter bandwidths and
  excitation patterns," J. Acoust. Soc. Am. 74, 750-753.


  Parameters
  ----------
  low_freq : float
    The center frequency in Hz of the lowest channel. The default is 100.
  high_freq : float
    The upper limit in Hz of the channel bank.  The center frequency
    of the highest channel will be below this frequency.
  n : int
    Number of channels. The default is 100.

  Returns
  -------
  cf_array : torch.Tensor
      An array of center frequencies, equally spaced on the ERB scale.

  """
  #  Change the following three parameters if you wish to use a different
  #  erb scale.  Must change in MakeerbCoeffs too.
  ear_q = 9.26449				# Glasberg and Moore Parameters
  min_bw = 24.7

  # All of the follow_freqing expressions are derived in Apple TR #35, "An
  # Efficient Implementation of the Patterson-Holdsworth Cochlear
  # Filter Bank."  See pages 33-34.
  cf_array = (-(ear_q*min_bw) + torch.exp(
      torch.arange(1, 1+n, dtype=torch.float64).unsqueeze(1) *
      (-math.log(high_freq + ear_q*min_bw) +
       math.log(low_freq + ear_q*min_bw))/n) * (high_freq + ear_q*min_bw))
  return cf_array


def make_erb_filters(fs: float, num_channels: int,
                     low_freq: float) -> List[torch.Tensor]:
  """Compute filter coefficients for a bank of Gammatone filters.

  The code is directly adapted from: 'Auditory Toolbox - An Efficient
  Implementation of the Patterson-Holdsworth Auditory Filter Bank' by
  Malcolm Slaney.

  The filter bank contains "num_channels" channels that extend from
  half the sampling rate (fs) to "low_freq".  Alternatively, if the
  num_channels argument is a vector, then the values of this vector are taken
  to be the center frequency of each desired filter.


  Parameters
  ----------
  fs : float
    Sampling rate (in Hz) of the filterbank (needed to determine CFs).
  num_channels : int or list of floats
    How many channels in the filterbank.
  low_freq : float
    The lowest center frequency of the filterbank.

  Returns
  -------
  fcoefs : List[torch.Tensor]
    A list of 10 num_channel-D arrays containing the filter parameters.

  """
  t = 1/fs
  if isinstance(num_channels, int):
    cf = erb_space(low_freq, fs/2, num_channels)
  else:
    cf = num_channels

  # Change the follow_freqing three parameters if you wish to use a different
  # erb scale.  Must change in ErbSpace too.
  ear_q = 9.26449				#  Glasberg and Moore Parameters
  min_bw = 24.7
  order = 1

  erb = ((cf/ear_q)**order + min_bw**order)**(1/order)

  b = 1.019*2*math.pi*erb

  a11 = -(2 * t * torch.cos(2 * cf * math.pi * t) / torch.exp(b * t) + 2 *
         math.sqrt(3 + 2**1.5) * t * torch.sin(2 * cf * math.pi * t) /
         torch.exp(b * t)) / 2
  a12 = -(2 * t * torch.cos(2 * cf * math.pi * t) / torch.exp(b * t) - 2 *
         math.sqrt(3 + 2**1.5) * t * torch.sin(2 * cf * math.pi * t) /
         torch.exp(b * t)) / 2
  a13 = -(2 * t * torch.cos(2 * cf * math.pi * t) / torch.exp(b * t) + 2 *
         math.sqrt(3 - 2**1.5) * t * torch.sin(2 * cf * math.pi * t) /
         torch.exp(b * t)) / 2
  a14 = -(2 * t * torch.cos(2 * cf * math.pi * t) / torch.exp(b * t) - 2 *
         math.sqrt(3 - 2**1.5) * t * torch.sin(2 * cf * math.pi * t) /
         torch.exp(b * t)) / 2

  gain = torch.abs((-2*torch.exp(4*complex(0, 1)*cf*math.pi*t)*t +
                    2*torch.exp(-(b*t) + 2*complex(0, 1)*cf*math.pi*t)*t *
                    (torch.cos(2*cf*math.pi*t) - math.sqrt(3 - 2**(3/2)) *
                     torch.sin(2*cf*math.pi*t))) *
                   (-2*torch.exp(4*complex(0, 1)*cf*math.pi*t)*t +
                    2*torch.exp(-(b*t) + 2*complex(0, 1)*cf*math.pi*t)*t *
                    (torch.cos(2*cf*math.pi*t) + math.sqrt(3 - 2**(3/2)) *
                       torch.sin(2*cf*math.pi*t))) *
                   (-2*torch.exp(4*complex(0, 1)*cf*math.pi*t)*t +
                    2*torch.exp(-(b*t) + 2*complex(0, 1)*cf*math.pi*t)*t *
                    (torch.cos(2*cf*math.pi*t) -
                       math.sqrt(3 + 2**(3/2))*torch.sin(2*cf*math.pi*t))) *
                   (-2*torch.exp(4*complex(0, 1)*cf*math.pi*t)*t +
                    2*torch.exp(-(b*t) + 2*complex(0, 1)*cf*math.pi*t)*t *
                    (torch.cos(2*cf*math.pi*t) +
                     math.sqrt(3 + 2**(3/2))*torch.sin(2*cf*math.pi*t))) /
                   (-2 / torch.exp(2*b*t) -
                    2*torch.exp(4*complex(0, 1)*cf*math.pi*t) +
                    2*(1 + torch.exp(4*complex(0, 1)*cf*math.pi*t)) /
                    torch.exp(b*t))**4)

  fcoefs = [t * torch.ones(len(cf), 1, dtype=torch.float64),
            a11, a12, a13, a14,
            0 * torch.ones(len(cf), 1, dtype=torch.float64),
            1 * torch.ones(len(cf), 1, dtype=torch.float64),
            -2*torch.cos(2*cf*math.pi*t)/torch.exp(b*t),
            torch.exp(-2*b*t),
            gain]

  return fcoefs




def prepare_coefficients(fcoefs: List[torch.Tensor]) -> torch.Tensor:
  r"""Reassemble filter coefficients to realize filters.

  Parameters
  ----------
  fcoefs : List[torch.Tensor]
      Coefficients prepared by make_erb_filters. 

  Returns
  -------
  sos : torch.Tensor
      Reassembled coefficients.

  """
  [a0, a11, a12, a13, a14, a2, b0, b1, b2, gain] = fcoefs
  n_chan = a0.shape[0]
  assert n_chan == a11.shape[0]
  assert n_chan == a12.shape[0]
  assert n_chan == a13.shape[0]
  assert n_chan == a14.shape[0]
  assert n_chan == b0.shape[0]
  assert n_chan == b1.shape[0]
  assert n_chan == gain.shape[0]

  sos = torch.cat([
      torch.cat([a0/gain,  a0,   a0, a0, b0], dim=1).unsqueeze(1),
      torch.cat([a11/gain, a12, a13, a14, b1], dim=1).unsqueeze(1),
      torch.cat([a2/gain,  a2,   a2, a2, b2], dim=1).unsqueeze(1),
  ], dim=1)

  return sos


def make_vowel(sample_len: int,
               pitch: float,
               sample_rate: float,
               f,
               bw=50) -> torch.Tensor:
  """Synthesize an artificial vowel using formant filters.

  The code is directly adapted from MakeVowel by Malcolm Slaney

  Make a vowel with "sample_len" samples and the given pitch. The
  formant frequencies are f1, f2 & f3.  Some common vowels are
            Vowel       f1      f2      f3
             /a/        730    1090    2440
             /i/        270    2290    3010
             /u/        300     870    2240

  The pitch variable can either be a scalar indicating the actual
  pitch frequency, or an array of impulse locations. Using an
  array of impulses allows this routine to compute vowels with
  varying pitch.

  Alternatively, f1 can be replaced with one of the following strings
  'a', 'i', 'u' and the appropriate formant frequencies are
  automatically selected.

  Parameters
  ----------
  sample_len : int
    How many samples to generate
  pitch : float
    Either a single floating point value indidcating a constant
    pitch (in Hz), or a train of impulses generated by fm_points.
  sample_rate : float
    The sample rate for the output signal (Hz)
  f : string or list
    Either a vowel spec, one of '/a/', '/i/', or '/u' or a list of
    (f1, f2, f3) where:
      f1: Is the frequency of the first formant.
      f2: Optional 2nd formant frequency
      f3: Optional 3rd formant frequency
  bw : width (in Hz) of the forman filter

  Returns
  -------
  y : torch.Tensor
      Waveform

  """
  f1, f2, f3 = 0., 0., 0.  # Keep Lint happy by setting defaults first.
  if isinstance(f, str):
    if f in ['a', '/a/']:
      f1, f2, f3 = (730, 1090, 2440)
    elif f in ['i', '/i/']:
      f1, f2, f3 = (270, 2290, 3010)
    elif f in ['u', '/u/']:
      f1, f2, f3 = (300, 870, 2240)
  elif isinstance(f, list) and len(f) == 3:
    f1, f2, f3 = f[0], f[1], f[2]
  elif isinstance(f, list) and len(f) == 2:
    f1, f2 = f[0], f[1]
    f3 = 0.
  elif isinstance(f, list) and len(f) == 1:
    f1 = f[0]
    f2 = 0.
    f3 = 0.
  # GlottalPulses(pitch, fs, sample_len) - Generate a stream of
  # glottal pulses with the given pitch (in Hz) and sampling
  # frequency (sample_rate).  A vector of the requested length is
  # returned.
  y = torch.zeros(sample_len, dtype=torch.float64)
  if isinstance(pitch, (int, float)):
    points = torch.arange(0, sample_len-1, sample_rate /
                          pitch, dtype=torch.float64)
  else:
    points = torch.sort(torch.as_tensor(pitch, dtype=torch.float64))[0]
    points = points[points < sample_len-1]

  indices = torch.floor(points).to(torch.int16)

  #  Use a triangular approximation to an impulse function.  The important
  #  part is to keep the total amplitude the same.
  y[(indices).tolist()] = (indices+1)-points
  y[(indices+1).tolist()] = points-indices

  # GlottalFilter(x,fs) - Filter an impulse train and simulate the glottal
  # transfer function.  The sampling interval (sample_rate) is given in Hz.
  # The filtering performed by this function is two first-order filters
  # at 250Hz.
  y = glottal_filter(sample_rate, y)

  #  FormantFilter - Filter an input sequence to model one
  #    formant in a speech signal.  The formant frequency (in Hz) is given
  #    by f and the bandwidth of the formant is a constant 50Hz.  The
  #    sampling frequency in Hz is given by fs.
  if f1 > 0:
    y = formant_filter(f1, sample_rate, y, bw)

  if f2 > 0:
    y = formant_filter(f2, sample_rate, y, bw)

  if f3 > 0:
    y = formant_filter(f3, sample_rate, y, bw)

  return y


def glottal_filter(sample_rate, x):
  """Glottal filter"""
  a = math.exp(-250*2*math.pi/sample_rate)
  return lfilter(x, torch.tensor([1, 0, -a*a], dtype=torch.float64),
                 torch.tensor([1, 0, 0], dtype=torch.float64), clamp=False)


def formant_filter(f, sample_rate, x, bw):
  """Filter with a formant filter."""
  cft = f/sample_rate
  q = f/bw
  rho = math.exp(-math.pi * cft / q)
  theta = 2 * math.pi * cft * math.sqrt(1-1/(4 * q*q))
  a2 = -2*rho*math.cos(theta)
  a3 = rho*rho
  a_coeffs = torch.tensor([1, a2, a3], dtype=torch.float64)
  b_coeffs = torch.tensor([1+a2+a3, 0, 0], dtype=torch.float64)
  return lfilter(x, a_coeffs, b_coeffs, clamp=False)


def fm_points(sample_len: int,
              freq: float,
              fm_freq: float = 6.,
              fm_amp: float = None,
              sampling_rate: float = 22050.) -> torch.Tensor:
  """Generate impulse train corresponding to a vibrato.

  The code is directly adapted from FMPoints by Malcolm Slaney

  Basic formula: phase angle = 2*pi*freq*t +
                          (fm_amp/fm_freq)*sin(2*pi*fm_freq*t)
      k-th zero crossing approximately at sample number
      (fs/freq)*(k - (fm_amp/(2*pi*fm_freq))*sin(2*pi*k*(fm_freq/freq)))

  Parameters
  ----------
  sample_len : int
    How much data to generate, in samples
  freq : float
    Base frequency of the output signal (Hz)
  fm_freq : float
    Vibrato frequency (in Hz)
  fm_amp : float
    Magnitude of the FM deviation (in Hz)
  sampling_rate : float
    Sample rate for the output signal.

  Returns
  -------
  y : torch.Tensor
    An impulse train, indicating the positive-going zero crossing
    of the phase funcion.

  """

  if fm_amp is None:
    fm_amp = 0.05*freq

  kmax = int(math.floor(freq*(sample_len/sampling_rate)))
  points = torch.arange(kmax, dtype=torch.float64)

  # The following is shifted back by one sample relative to FMPoints.m in the
  # Matlab toolbox.
  y = (sampling_rate/freq)*(points-(
    fm_amp/(2*math.pi*fm_freq))*torch.sin(2*math.pi*(fm_freq/freq)*points))

  return y



def correlogram_frame(data: torch.Tensor, pic_width: int,
                      start: int = 0, win_len: int = 0,
                      dtype: Optional[torch.dtype] = torch.float64,
                      ) -> torch.Tensor:
  """Generate one frame of a correlogram using FFTs to compute autocorrelation.

  Example:
  ----------
      import torch
      import math
      c = torch.zeros(20,256,dtype=torch.float64)
      for j in torch.arange(20,0,-1):
          t = torch.arange(1,257,dtype=torch.float64)
          c[j-1,:] = torch.nn.ReLU()(torch.sin(t/256*(21-j)*3*2*math.pi))
      picture = correlogram_frame(c,128,0,256)


  Parameters
  ----------
  data : torch.Tensor
    A (num_channel x time) or (..., num_channel x time) array of input
    waveforms, one time domain signal per channel.
  pic_width : int
    Number of pixels (time lags) in the final correlogram frame.
  start : int
    The starting sample
  win_len : int
    How much data to take from the input signal when computing the
    autocorrelation.
  dtype : Optional[torch.dtype], optional
    The default is torch.float64.

  Returns
  -------
  pic : torch.Tensor
    An array of size (num_channels x pic_width) containing one
    frame of the correlogram. If input has size (..., num_channel x time) then
    output will be of size (..., num_channels x pic_width).

  """
  input_dimensions = list(data.shape)
  data_len = input_dimensions[-1]
  if not win_len:
    win_len = data_len

  # Round up to double the window size, and then the next power of 2.
  fft_size = int(2**(math.ceil(math.log2(2*max(pic_width, win_len)))))

  start = max(0, start)
  last = min(data_len, start+win_len)

  # Generate a window that is win_len long
  a = .54
  b = -.46
  wr = math.sqrt(64/256)
  phi = math.pi/win_len
  ws = 2*wr/math.sqrt(4*a*a+2*b*b)*(
    a + b*torch.cos(2*math.pi*(torch.arange(win_len, dtype=dtype))/win_len
                    + phi))

  # Intialize output
  output_dimensions =  list(data.shape)
  output_dimensions[-1] = fft_size
  f = torch.zeros(output_dimensions, dtype=dtype)

  f[..., :(last-start)] = data[..., start:last] * ws[:(last-start)]
  # pylint: disable=not-callable
  f = torch.fft.fft(f, axis=-1)
  # pylint: disable=not-callable
  f = torch.fft.ifft(f * torch.conj(f), axis=-1)

  # Output pic
  pic = torch.maximum(torch.tensor(0.0), torch.real(f[..., :pic_width]))

  # Make sure first column is bigger than the rest
  good_rows = torch.logical_and((pic[..., 0] > 0),
                                torch.logical_and((pic[..., 0] > pic[..., 1]),
                                (pic[..., 0] > pic[..., 2])))

  # Define that pic is normalized by sqrt(pic[...,0]). Define further that
  # zero entries and bad rows are masked out.
  norm_factor = torch.zeros_like(pic)
  norm_factor[good_rows] = 1./torch.sqrt(pic[good_rows][...,[0]])
  pic = pic * norm_factor

  return pic



def correlogram_array(data: torch.Tensor, sampling_rate: float,
                     frame_rate: int = 12, width: int = 256,
                     dtype: Optional[torch.dtype] = torch.float64,
                     ) -> torch.Tensor:
  """Generate an array of correlogram frames.

  Parameters
  ----------
  data : torch.Tensor
    The filterbank's output, size (num_channel x time) or
    (..., num_channel x time)
  sampling_rate : float
    The sample rate for the data (needed when computing the frame times)
  frame_rate : int
    How often (in Hz) correlogram frames should be generated.
  width: int
    The width (in lags) of the correlogram
  dtype : Optional[torch.dtype], optional
    The default is torch.float64.

  Returns
  -------
  movie : torch.Tensor
    A (num_frames x num_channels x width) tensor or a
    (..., num_frames x num_channels x width) tensor of correlogram frames.

  """
  if data.ndim==2:
    data = data.unsqueeze(-2)
  sample_len = data.shape[-1]
  frame_increment = int(sampling_rate/frame_rate)
  frame_count = int((sample_len-width)/frame_increment) + 1

  movie = []
  for i in range(frame_count):
    start = i*frame_increment
    frame = correlogram_frame(data,
                              pic_width = width,
                              start = start,
                              win_len = frame_increment*4,
                              dtype = dtype).unsqueeze(-3)
    movie.append(frame)
  movie = torch.cat(movie,dim=-3)
  return movie




def correlogram_pitch(correlogram: torch.Tensor,
                      width: int = 256,
                      sr: float = 22254.54,
                      low_pitch: float = 0.,
                      high_pitch: float = 20000.,
                      dtype: Optional[torch.dtype] = torch.float64,
                      ) -> Tuple[torch.Tensor,torch.Tensor]:
  """Compute the summary of a correlogram to find the pitch.

  Computes the pitch of a correlogram sequence by finding the time lag
  with the largest correlation energy.

  The correlogram_pitch function uses optional low_pitch and high_pitch
  arguments to limit the range of legal pitch values. It is important to
  note that correlogram_pitch do not include any other higher-level knowledge
  about pitch. Notably, this work does not enforce any frame-to-frame
  continuity in the pitch. Each pitch estimate is independent and there
  is no restriction preventing the estimate to change instantaneously from
  frame to frame.

  Parameters
  ----------
  correlogram : torch.Tensor
    A 3D correlogram array, output from correlogram_array of size
    (num_frames x num_channels x num_times)
  width : int
    Width of the correlogram.  Historical parameter. Should be
    equal to correlogram.shape[1]. The default is 256
  sr : float
    The sample rate. The default is 22254.54.
  low_pitch : float
    Lowest allowable pitch (Hz). Pitch peaks are only searched
    within the region low_pitch to high_pitch. The default is 0.
  high_pitch : float
    The default is 20000..
  dtype : Optional[torch.dtype], optional
    The default is torch.float64.

  Raises
  ------
  TypeError
    The input data has be of size (num_frames x num_channels x num_times).

  Returns
  -------
  pitch : torch.Tensor
    A one-dimensional tensor of length num_frames indicating the pitch
    or 0 if no pitch is found.
  salience : torch.Tensor
    A one-dimensional tensor indicating the pitch salience on a scale
    from 0 (no pitch found) to 1 clear pitch.

  """
  if not correlogram.ndim == 3:
    raise TypeError('Input should be (num_frames x num_channels x num_times)')

  drop_low = int(sr/high_pitch)
  if low_pitch > 0:
    drop_high = int(min(width, math.ceil(sr/low_pitch)))
  else:
    drop_high = width

  frames = correlogram.shape[-3]

  pitch = torch.zeros(frames, dtype=dtype)
  salience = torch.zeros(frames, dtype=dtype)
  for j in range(frames):
    # Get one frame from the correlogram and compute
    # the sum (as a function of time lag) across all channels.
    summary = torch.sum(correlogram[j, :, :], axis=0)
    zero_lag = torch.sum(correlogram[j, :, :], axis=0)[0]
    # Now we need to find the first pitch past the peak at zero
    # lag.  The following lines smooth the summary pitch a bit, then
    # look for the first point where the summary goes back up.
    # Everything up to this point is zeroed out.
    window_length = 16
    b_coefs = torch.ones(window_length, dtype=dtype)
    a_coefs = torch.zeros(window_length, dtype=dtype)
    a_coefs[0] = 1.
    sumfilt = lfilter(summary, a_coefs, b_coefs, clamp=False, batching=True)

    sumdif = sumfilt[..., 1:width] - sumfilt[..., :width-1]
    sumdif[:window_length] = 0
    valleys = torch.argwhere(sumdif > 0)
    summary[:int(valleys[0, 0])] = 0
    summary[1:drop_low] = 0
    summary[drop_high:] = 0

    # Now find the location of the biggest peak and call this the pitch
    p = torch.argmax(summary)
    if p > 0:
      pitch[j] = sr/float(p)

    salience[j] = summary[p]/zero_lag

  return pitch, salience

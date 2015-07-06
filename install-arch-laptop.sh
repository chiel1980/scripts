#!/bin/bash
#
#
#
###########################
#
### Install packages
#
packages=(midori connman midori parcellite gnome-keyring synaptics xorg-server xorg-xinit i3 vlc libreoffice fish mutt curl lynx atom connman-ui-gtk terminator urxvt git)
dotfiles_url='https://github.com/chiel1980/dotfiles.git'
function install_packages {
pacman -Sy $packages
}
  install_packages 
#
### Get our dotfiles from github
#
mkdir tmp
cd tmp
git clone $dotfiles_url
#
### Place our .dotfiles in the right location
#
cp -rp .*   ~/
cp fish_prompt.fish ~/.config/fish/functions/
#
### Ensure that all services are started
#
systemctl enable connman.service
systemctl start connman.service
